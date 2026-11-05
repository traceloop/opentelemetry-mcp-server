"""Datadog backend implementation using the Spans API (v2).

Unlike Jaeger/Tempo/Traceloop, Datadog's public API is span-centric rather than
trace-centric: there is no "get trace by ID" endpoint. A trace is reconstructed
by searching spans filtered by ``trace_id`` and grouping the results. Search
uses Datadog's span search query syntax (the same syntax that powers the Logs
Explorer - see https://docs.datadoghq.com/logs/explorer/search_syntax/),
not TraceQL or Jaeger-style tag params.

Schema note: this implementation is grounded in Datadog's published OpenAPI
spec (SpansListRequest/SpansListResponse/SpansAttributes in
https://github.com/DataDog/datadog-api-client-python/blob/master/.generator/schemas/v2/openapi.yaml)
rather than guessed field names. Two things the spec does not pin down, and
that could not be verified without a live Datadog account:

1. Where OTel ``gen_ai.*``/error attributes land in the response - the
   documented ``SpansAttributes`` has a generic ``attributes`` (custom
   attributes) object and a ``tags`` array, but doesn't document exactly how
   OTLP-ingested span attributes are split between the two. This
   implementation checks both.
2. There's no documented first-class ``status``/``error`` field on a span
   resource. Error state is inferred from common signals (an ``error`` custom
   attribute, an ``error:*``-prefixed tag, or standard ``error.type``/
   ``error.message`` OTel attributes).

Both are flagged again at the call sites below. Someone with a live Datadog
account and real gen_ai-instrumented traces should verify against actual
payloads before merge.
"""

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from opentelemetry_mcp.attributes import HealthCheckResponse, SpanAttributes, SpanEvent
from opentelemetry_mcp.backends.base import BaseBackend
from opentelemetry_mcp.backends.filter_engine import FilterEngine
from opentelemetry_mcp.constants import Fields
from opentelemetry_mcp.models import (
    Filter,
    FilterOperator,
    SpanData,
    SpanQuery,
    TraceData,
    TraceQuery,
)

logger = logging.getLogger(__name__)

# Datadog search syntax fields that are query facets rather than custom
# attributes - these are queried bare (`service:foo`), everything else is
# queried with an `@` prefix (`@gen_ai.system:foo`), matching Datadog's Logs
# Explorer / span search convention for custom vs. reserved attributes.
_FACET_FIELDS = {
    Fields.SERVICE_NAME: "service",
    Fields.OPERATION_NAME: "resource_name",
}

# Default lookback window used when a query has no time range and there is no
# narrower signal (e.g. get_trace, list_services). Datadog's span search
# requires filter.from/filter.to. 30 days matches the upper end of Datadog's
# commonly documented standard APM retention (15 or 30 days depending on the
# account's retention filter) - a shorter default risked reporting a
# genuinely-retained-but-older trace as not found. If an account has a custom
# retention filter longer than 30 days, this will still miss traces beyond
# that window.
_DEFAULT_LOOKBACK = timedelta(days=30)

_MAX_TRACES_TO_HYDRATE = 50

# Safety bound on how many pages _search_spans_raw will follow via Datadog's
# cursor pagination for a single logical search (each page up to 1000 spans,
# Datadog's own per-page max), so a pathological query can't loop forever.
_MAX_SEARCH_PAGES = 10


class DatadogBackend(BaseBackend):
    """Datadog Spans API (v2) backend."""

    def __init__(
        self,
        url: str,
        api_key: str | None = None,
        app_key: str | None = None,
        timeout: float = 30.0,
    ):
        """Initialize Datadog backend.

        Args:
            url: Datadog site API base URL (e.g. https://api.datadoghq.com or
                https://api.datadoghq.eu for the EU site)
            api_key: Datadog API key (required)
            app_key: Datadog Application key (required - trace/span queries
                need both, unlike simple ingestion which only needs api_key)
            timeout: Request timeout in seconds
        """
        super().__init__(url, api_key, timeout)

        if not self.url.startswith("https://"):
            raise ValueError(
                "Datadog backend requires an https:// URL - DD-API-KEY and "
                "DD-APPLICATION-KEY must not be sent over plain http"
            )
        if not self.api_key:
            raise ValueError("Datadog backend requires an API key (BACKEND_API_KEY)")
        if not app_key:
            raise ValueError(
                "Datadog backend requires an Application key (BACKEND_APP_KEY) "
                "in addition to the API key"
            )

        self.app_key = app_key

    @property
    def client(self) -> httpx.AsyncClient:
        """Get or create HTTP client with connection pooling.

        Overrides BaseBackend to disable automatic redirect-following.
        DD-API-KEY/DD-APPLICATION-KEY are non-standard headers that httpx
        does not strip on cross-origin redirects (unlike Authorization/
        Cookie/Proxy-Authorization), so following a redirect to an
        unexpected host would leak both credentials there.

        Returns:
            Reusable AsyncClient instance with automatic connection pooling
        """
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.url,
                headers=self._create_headers(),
                timeout=self.timeout,
                follow_redirects=False,
            )
        return self._client

    def _create_headers(self) -> dict[str, str]:
        """Create headers for Datadog API requests.

        Returns:
            Dictionary with DD-API-KEY, DD-APPLICATION-KEY, and Content-Type
        """
        return {
            "DD-API-KEY": self.api_key or "",
            "DD-APPLICATION-KEY": self.app_key,
            "Content-Type": "application/json",
        }

    def get_supported_operators(self) -> set[FilterOperator]:
        """Get natively supported operators via Datadog span search syntax.

        Returns:
            Set of supported FilterOperator values
        """
        return {
            FilterOperator.EQUALS,
            FilterOperator.NOT_EQUALS,
            FilterOperator.GT,
            FilterOperator.LT,
            FilterOperator.GTE,
            FilterOperator.LTE,
            FilterOperator.EXISTS,
            FilterOperator.NOT_EXISTS,
            FilterOperator.IN,
        }

    async def search_traces(self, query: TraceQuery) -> list[TraceData]:
        """Search traces by searching spans and hydrating each matching trace.

        Datadog has no trace-level search endpoint, so this searches spans
        matching the query, then re-fetches the full span set for each
        distinct trace_id found (mirroring the Tempo backend's
        search-then-hydrate approach) so a partial/filtered span match still
        yields a complete trace.

        The initial span search is used only to discover candidate
        trace_ids - it is not trusted to have applied the query's filters
        correctly at the trace level. A native filter can match because one
        arbitrary child span satisfied it, which says nothing about whether
        the *reconstructed trace* actually satisfies a trace-level query
        (e.g. `service_name` here means "the trace's root service", not
        "any span in the trace"). Every filter is therefore re-applied via
        FilterEngine against the fully-hydrated trace before returning.

        Args:
            query: Trace query parameters

        Returns:
            List of matching traces with all spans

        Raises:
            httpx.HTTPError: If the API request fails
        """
        all_filters = query.get_all_filters()
        supported_operators = self.get_supported_operators()
        native_filters = [f for f in all_filters if f.operator in supported_operators]

        dd_query, _ = self._build_dd_query(native_filters)
        start, end = self._time_range(query.start_time, query.end_time)

        spans_data = await self._search_spans_raw(dd_query, start, end, query.limit * 5)

        trace_ids: list[str] = []
        seen: set[str] = set()
        for span_obj in spans_data:
            trace_id = span_obj.get("attributes", {}).get("trace_id")
            if trace_id and trace_id not in seen:
                seen.add(trace_id)
                trace_ids.append(trace_id)

        max_to_fetch = min(len(trace_ids), _MAX_TRACES_TO_HYDRATE)
        if len(trace_ids) > max_to_fetch:
            logger.warning(
                f"Limiting trace fetch to {max_to_fetch} out of {len(trace_ids)} "
                f"results to avoid excessive API calls"
            )

        traces: list[TraceData] = []
        for trace_id in trace_ids[:max_to_fetch]:
            try:
                traces.append(await self.get_trace(trace_id))
            except Exception as e:
                logger.warning(f"Failed to fetch trace {trace_id}: {e}")

        # Re-verify every filter (not just the ones Datadog couldn't apply)
        # against the fully-hydrated trace - see docstring.
        if all_filters:
            traces = FilterEngine.apply_filters(traces, all_filters)

        return traces[: query.limit]

    async def search_spans(self, query: SpanQuery) -> list[SpanData]:
        """Search for individual spans matching the query.

        Args:
            query: Span query parameters

        Returns:
            List of matching spans

        Raises:
            httpx.HTTPError: If the API request fails
        """
        all_filters = query.get_all_filters()
        supported_operators = self.get_supported_operators()
        native_filters = [f for f in all_filters if f.operator in supported_operators]
        client_filters = [f for f in all_filters if f.operator not in supported_operators]

        dd_query, unconverted = self._build_dd_query(native_filters)
        # A filter whose operator Datadog supports in principle can still
        # fail to convert (e.g. a range operator with a non-numeric operand)
        # and be silently dropped from dd_query - fall back to client-side
        # filtering for those instead of treating them as satisfied.
        client_filters = client_filters + unconverted

        if client_filters:
            logger.info(
                f"Will apply {len(client_filters)} span filters client-side: "
                f"{[(f.field, f.operator.value) for f in client_filters]}"
            )

        start, end = self._time_range(query.start_time, query.end_time)

        spans_data = await self._search_spans_raw(dd_query, start, end, query.limit * 2)

        spans: list[SpanData] = []
        for span_obj in spans_data:
            span = self._parse_dd_span(span_obj)
            if span:
                spans.append(span)

        if client_filters:
            spans = FilterEngine.apply_filters(spans, client_filters)

        return spans[: query.limit]

    async def get_trace(self, trace_id: str) -> TraceData:
        """Get a specific trace by ID by searching all spans sharing it.

        Args:
            trace_id: Trace identifier

        Returns:
            Complete trace data with all spans

        Raises:
            ValueError: If no spans are found for the trace ID
            httpx.HTTPError: If the API request fails
        """
        start, end = self._time_range(None, None, lookback=_DEFAULT_LOOKBACK)
        # trace_id can originate from an external MCP tool call - escape and
        # exact-quote it rather than interpolating it raw into the query, so
        # it can't inject additional query clauses.
        dd_query = f"trace_id:{self._escape_dd_query_value(trace_id)}"

        # get_trace's contract is "the complete trace", unlike the sampling/
        # search operations elsewhere in this backend - so its target span
        # count matches _search_spans_raw's own full pagination capacity
        # rather than a single page. A trace with more spans than that would
        # still truncate, logged by _search_spans_raw itself.
        spans_data = await self._search_spans_raw(
            dd_query, start, end, limit=_MAX_SEARCH_PAGES * 1000
        )

        spans: list[SpanData] = []
        for span_obj in spans_data:
            span = self._parse_dd_span(span_obj)
            # Belt-and-suspenders: only keep spans that exactly match the
            # requested trace_id, in case the query above ever matches more
            # broadly than intended.
            if span and span.trace_id == trace_id:
                spans.append(span)

        if not spans:
            raise ValueError(f"No spans found for trace {trace_id}")

        return self._group_into_trace(trace_id, spans)

    async def list_services(self) -> list[str]:
        """List all available services by sampling recent spans.

        Datadog's Spans API has no dedicated "list services" endpoint, so
        this searches a broad recent window and extracts unique service
        names client-side, matching the Tempo backend's fallback approach.

        Returns:
            List of service names

        Raises:
            httpx.HTTPError: If the API request fails
        """
        logger.debug("Listing services")
        start, end = self._time_range(None, None)

        spans_data = await self._search_spans_raw("*", start, end, limit=1000)

        services: set[str] = set()
        for span_obj in spans_data:
            service = span_obj.get("attributes", {}).get("service")
            if service:
                services.add(service)

        result = sorted(services)
        logger.debug(f"Found {len(result)} unique services from {len(spans_data)} spans")
        return result

    async def get_service_operations(self, service_name: str) -> list[str]:
        """Get operations (resource names) for a service.

        Args:
            service_name: Service name

        Returns:
            List of operation names

        Raises:
            httpx.HTTPError: If the API request fails
        """
        logger.debug(f"Getting operations for service: {service_name}")
        start, end = self._time_range(None, None)

        dd_query = f"service:{self._escape_dd_query_value(service_name)}"
        spans_data = await self._search_spans_raw(dd_query, start, end, limit=1000)

        operations: set[str] = set()
        for span_obj in spans_data:
            resource_name = span_obj.get("attributes", {}).get("resource_name")
            if resource_name:
                operations.add(resource_name)

        return sorted(operations)

    async def health_check(self) -> HealthCheckResponse:
        """Check Datadog backend health via a minimal span search.

        Returns:
            Health status information
        """
        logger.debug("Checking backend health")

        try:
            start, end = self._time_range(None, None)
            await self._search_spans_raw("*", start, end, limit=1)

            return HealthCheckResponse(
                status="healthy",
                backend="datadog",
                url=self.url,
            )
        except Exception as e:
            return HealthCheckResponse(
                status="unhealthy",
                backend="datadog",
                url=self.url,
                error=str(e),
            )

    # -- internal helpers ---------------------------------------------------

    async def _search_spans_raw(
        self, dd_query: str, start: datetime, end: datetime, limit: int
    ) -> list[dict[str, Any]]:
        """Call the Datadog Spans search endpoint, following pagination.

        Datadog caps a single page at 1000 spans (`meta.page.after` is the
        cursor for the next one). This follows that cursor across multiple
        requests until either `limit` spans have been collected or the API
        stops returning a continuation cursor, bounded by
        `_MAX_SEARCH_PAGES` so a pathological query can't loop indefinitely.

        Args:
            dd_query: Datadog span search query string
            start: Start of the search window
            end: End of the search window
            limit: Target total number of spans to collect

        Returns:
            List of raw ``Span`` objects (each with ``id``/``type``/``attributes``)

        Raises:
            httpx.HTTPError: If the API request fails
        """
        collected: list[dict[str, Any]] = []
        cursor: str | None = None

        for _ in range(_MAX_SEARCH_PAGES):
            remaining = limit - len(collected)
            if remaining <= 0:
                break

            page: dict[str, Any] = {"limit": min(max(remaining, 1), 1000)}
            if cursor:
                page["cursor"] = cursor

            body = {
                "data": {
                    "type": "search_request",
                    "attributes": {
                        "filter": {
                            "query": dd_query,
                            "from": start.isoformat(),
                            "to": end.isoformat(),
                        },
                        "page": page,
                        "sort": "-timestamp",
                    },
                }
            }

            response = await self.client.post("/api/v2/spans/events/search", json=body)
            response.raise_for_status()

            data = response.json()

            # A 200 response with an unexpected shape (a scalar/list body, a
            # non-list `data`, a non-dict entry within it, or a non-dict
            # `meta`/`meta.page`) would otherwise crash here or get bad
            # entries extended into `collected`. Validate defensively at
            # each navigation step instead of trusting the shape.
            if not isinstance(data, dict):
                logger.warning(
                    f"Datadog search response body was not an object "
                    f"(got {type(data).__name__}); treating as empty"
                )
                break

            page_items = data.get("data", [])
            if not isinstance(page_items, list):
                logger.warning(
                    f"Datadog search response 'data' was not a list "
                    f"(got {type(page_items).__name__}); treating as empty"
                )
                page_items = []
            # Every consumer of `collected` (search_traces, search_spans,
            # get_trace, list_services, get_service_operations) does
            # `item.get("attributes", {}).get(...)` directly, without going
            # through _parse_dd_span's own try/except - so an item whose
            # `attributes` value is present but not a dict (e.g.
            # `{"attributes": "bad"}`) must be excluded here too, not just a
            # non-dict item itself.
            collected.extend(
                item
                for item in page_items
                if isinstance(item, dict) and isinstance(item.get("attributes"), dict)
            )

            meta = data.get("meta")
            page_meta = meta.get("page") if isinstance(meta, dict) else None
            cursor = page_meta.get("after") if isinstance(page_meta, dict) else None
            if not isinstance(cursor, str) or not cursor:
                break
        else:
            logger.warning(
                f"Stopped after {_MAX_SEARCH_PAGES} pages with more results available "
                f"(query: {dd_query!r}); results may be incomplete"
            )

        return collected

    def _time_range(
        self,
        start_time: datetime | None,
        end_time: datetime | None,
        lookback: timedelta = _DEFAULT_LOOKBACK,
    ) -> tuple[datetime, datetime]:
        """Resolve a query's time range, defaulting to a lookback window.

        Args:
            start_time: Explicit start time, if any
            end_time: Explicit end time, if any
            lookback: Default window size when start_time is not given

        Returns:
            (start, end) tuple, both timezone-aware
        """
        end = end_time or datetime.now(UTC)
        start = start_time or (end - lookback)
        return start, end

    def _build_dd_query(self, filters: list[Filter]) -> tuple[str, list[Filter]]:
        """Build a Datadog span search query string from Filter objects.

        Args:
            filters: List of Filter conditions

        Returns:
            Tuple of (Datadog span search query string, defaults to "*" if no
            conditions converted) and the subset of `filters` that could not
            be converted to a native condition (e.g. a range operator with a
            non-numeric operand) and so were silently dropped from the query
            rather than applied - callers must apply these another way.
        """
        conditions: list[str] = []
        unconverted: list[Filter] = []
        for filter_obj in filters:
            condition = self._filter_to_dd_query(filter_obj)
            if condition is None:
                unconverted.append(filter_obj)
            else:
                conditions.append(condition)

        query = " AND ".join(conditions) if conditions else "*"
        return query, unconverted

    def _dd_field(self, field: str) -> str:
        """Map an internal field name to its Datadog search syntax name.

        Args:
            field: Internal field name (e.g. "service.name", "gen_ai.system")

        Returns:
            Datadog facet name (bare) or custom attribute name (`@`-prefixed)
        """
        if field in _FACET_FIELDS:
            return _FACET_FIELDS[field]
        if field == Fields.STATUS:
            return "status"
        if field == Fields.DURATION:
            return "@duration"
        # Custom/OTel attributes (gen_ai.*, arbitrary tags) are queried with
        # the `@` prefix per Datadog's search syntax for non-facet attributes.
        return f"@{field}"

    def _escape_dd_query_value(self, value: str) -> str:
        """Escape and exact-quote a value for safe interpolation into a query.

        Always quotes and escapes embedded quotes/backslashes, rather than
        only quoting for readability when a term contains whitespace. Used
        for every value interpolated into a Datadog query - filter values,
        service names, and trace_id - since any of them can originate from
        external input (e.g. an MCP tool call's argument) and must not be
        able to inject additional query clauses.

        Args:
            value: Raw value to interpolate

        Returns:
            A double-quoted, escaped Datadog query term
        """
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'

    def _filter_to_dd_query(self, filter_obj: Filter) -> str | None:
        """Convert a single Filter to a Datadog span search condition.

        Args:
            filter_obj: Filter to convert

        Returns:
            Datadog search condition string, or None if unsupported
        """
        field = self._dd_field(filter_obj.field)
        operator = filter_obj.operator
        value = filter_obj.value
        values = filter_obj.values

        is_duration = field == "@duration"
        # Datadog's @duration facet is in nanoseconds; the rest of this
        # codebase works in milliseconds.
        scale = 1_000_000 if is_duration else 1

        if operator == FilterOperator.EQUALS:
            # Datadog's status facet is lowercase ("ok", "error"); Filter.value
            # isn't constrained to match that casing (it's a freeform
            # str|int|float|bool from any caller), so normalize rather than
            # whitelisting specific literal casings like "OK"/"ERROR". Values
            # this codebase's own status model allows but Datadog's facet
            # doesn't (e.g. "UNSET") can't be expressed as a native query at
            # all - return None so the caller falls back to client-side
            # filtering instead of sending a query that can never match.
            v = value.lower() if field == "status" and isinstance(value, str) else value
            if field == "status" and v not in ("ok", "error"):
                return None
            v = v * scale if isinstance(v, int | float) else v
            return f"{field}:{self._escape_dd_query_value(str(v))}"

        elif operator == FilterOperator.NOT_EQUALS:
            v = value.lower() if field == "status" and isinstance(value, str) else value
            if field == "status" and v not in ("ok", "error"):
                return None
            v = v * scale if isinstance(v, int | float) else v
            return f"-{field}:{self._escape_dd_query_value(str(v))}"

        elif operator in (
            FilterOperator.GT,
            FilterOperator.GTE,
            FilterOperator.LT,
            FilterOperator.LTE,
        ):
            # Filter.value_type isn't enforced against the actual Python type
            # of `value`, so a range operator could arrive with a string -
            # interpolating that unchecked into a numeric range expression
            # would let it alter or invalidate the query. Reject non-numeric
            # operands instead.
            if not isinstance(value, int | float) or isinstance(value, bool):
                logger.warning(
                    f"Skipping non-numeric value for {operator.value} on {field!r}: {value!r}"
                )
                return None
            v = value * scale
            if operator == FilterOperator.GT:
                return f"{field}:{{{v} TO *}}"
            elif operator == FilterOperator.GTE:
                return f"{field}:[{v} TO *]"
            elif operator == FilterOperator.LT:
                return f"{field}:{{* TO {v}}}"
            else:
                return f"{field}:[* TO {v}]"

        elif operator == FilterOperator.EXISTS:
            return f"{field}:*"

        elif operator == FilterOperator.NOT_EXISTS:
            return f"-{field}:*"

        elif operator == FilterOperator.IN:
            if not values:
                return None
            # Datadog's status facet values are lowercase ("ok", "error");
            # normalize the same way the EQUALS/NOT_EQUALS branches do,
            # every other field is passed through unchanged.
            is_status = field == "status"
            if is_status:
                normalized = [str(v).lower() for v in values]
                # A value outside ok/error (e.g. "UNSET") can't be expressed
                # as a native query at all - fall back to client-side
                # filtering for the whole IN rather than silently omitting
                # just that one value from the OR.
                if any(v not in ("ok", "error") for v in normalized):
                    return None
                or_terms = [f"{field}:{self._escape_dd_query_value(v)}" for v in normalized]
            else:
                or_terms = [f"{field}:{self._escape_dd_query_value(str(v))}" for v in values]
            return "(" + " OR ".join(or_terms) + ")"

        logger.warning(f"Unsupported operator for Datadog query: {operator}")
        return None

    def _parse_dd_span(self, span_obj: dict[str, Any]) -> SpanData | None:
        """Parse a raw Datadog Span resource into SpanData.

        Args:
            span_obj: Raw ``Span`` object from the search response

        Returns:
            Parsed SpanData, or None if required fields are missing
        """
        try:
            attrs = span_obj.get("attributes", {})
            trace_id = attrs.get("trace_id")
            span_id = attrs.get("span_id")
            if not trace_id or not span_id:
                return None

            # Datadog uses "0" as the sentinel parent_id for root spans.
            parent_id_raw = attrs.get("parent_id")
            parent_span_id = parent_id_raw if parent_id_raw and parent_id_raw != "0" else None

            start_time = self._parse_dd_timestamp(attrs.get("start_timestamp"))
            end_time = self._parse_dd_timestamp(attrs.get("end_timestamp"))
            if start_time is None or end_time is None:
                # Don't fabricate timing data: a substituted "now" start time
                # or a zero duration would silently corrupt trace ordering
                # and duration aggregation for anything that reads this span.
                logger.warning(
                    f"Rejecting span {span_id} (trace {trace_id}): missing or "
                    "invalid start_timestamp/end_timestamp"
                )
                return None
            duration_ms = (end_time - start_time).total_seconds() * 1000

            custom_attrs = attrs.get("attributes", {}) or {}
            tags = attrs.get("tags", []) or []

            status = self._infer_status(custom_attrs, tags)
            span_attributes = SpanAttributes(**self._extract_semconv_attributes(custom_attrs))

            events: list[SpanEvent] = []

            return SpanData(
                trace_id=str(trace_id),
                span_id=str(span_id),
                parent_span_id=str(parent_span_id) if parent_span_id else None,
                operation_name=attrs.get("resource_name") or attrs.get("service", "unknown"),
                service_name=attrs.get("service", "unknown"),
                start_time=start_time,
                duration_ms=duration_ms,
                status=status,
                attributes=span_attributes,
                events=events,
            )
        except Exception as e:
            logger.error(f"Error parsing Datadog span: {e}")
            return None

    def _parse_dd_timestamp(self, value: str | None) -> datetime | None:
        """Parse a Datadog ISO8601 timestamp string.

        Args:
            value: Timestamp string (e.g. "2023-01-02T09:42:36.420Z")

        Returns:
            Parsed timezone-aware datetime, or None
        """
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            logger.warning(f"Could not parse Datadog timestamp: {value}")
            return None

    def _infer_status(self, custom_attrs: dict[str, Any], tags: list[str]) -> Any:
        """Best-effort error/status inference.

        Datadog's documented Span resource has no first-class status/error
        field (see module docstring) - this checks the signals actually
        documented elsewhere in Datadog's product (an `error` custom
        attribute, an `error:*`-prefixed tag, or `error.type`/`error.message`
        OTel attributes) and defaults to UNSET rather than guessing OK, since
        an unrecognized shape should not silently read as a passing span.

        Args:
            custom_attrs: The span's custom/OTel attributes object
            tags: The span's tag list

        Returns:
            "ERROR", "OK", or "UNSET"
        """
        if custom_attrs.get("error") in (True, "true", 1):
            return "ERROR"
        if any(k in custom_attrs for k in ("error.type", "error.message", "error.stack")):
            return "ERROR"
        for tag in tags:
            if tag == "error:true" or tag.startswith("error.type:"):
                return "ERROR"
        if custom_attrs.get("error") in (False, "false", 0):
            return "OK"
        return "UNSET"

    def _extract_semconv_attributes(self, custom_attrs: dict[str, Any]) -> dict[str, Any]:
        """Extract known gen_ai.*/llm.* semantic-convention keys for SpanAttributes.

        Handles both a flat dotted-key shape (`{"gen_ai.system": "openai"}`)
        and a nested-object shape (`{"gen_ai": {"system": "openai"}}`), since
        which one Datadog's OTLP intake produces for a given attribute is not
        pinned down by the public schema (see module docstring).

        Args:
            custom_attrs: The span's custom/OTel attributes object

        Returns:
            Dict of dotted-key attributes, suitable for SpanAttributes(**...)
        """
        flat: dict[str, Any] = {}

        def walk(prefix: str, obj: Any) -> None:
            if isinstance(obj, dict):
                for k, v in obj.items():
                    key = f"{prefix}.{k}" if prefix else k
                    walk(key, v)
            else:
                flat[prefix] = obj

        walk("", custom_attrs)
        return flat

    def _group_into_trace(self, trace_id: str, spans: list[SpanData]) -> TraceData:
        """Group a flat list of spans belonging to one trace into TraceData.

        Args:
            trace_id: The trace ID all spans share
            spans: All spans for this trace

        Returns:
            Assembled TraceData
        """
        root_spans = [s for s in spans if not s.parent_span_id]
        root_span = root_spans[0] if root_spans else spans[0]

        start_times = [s.start_time for s in spans]
        end_times = [
            datetime.fromtimestamp(
                s.start_time.timestamp() + (s.duration_ms / 1000), tz=s.start_time.tzinfo
            )
            for s in spans
        ]
        trace_start = min(start_times)
        trace_end = max(end_times)
        trace_duration_ms = (trace_end - trace_start).total_seconds() * 1000

        # Preserve UNSET rather than defaulting to OK: most spans reaching
        # here already carry UNSET from _infer_status's best-effort guess,
        # and "no span confirmed an error" is not the same claim as "every
        # span confirmed success."
        if any(s.has_error for s in spans):
            trace_status: Any = "ERROR"
        elif all(s.status == "OK" for s in spans):
            trace_status = "OK"
        else:
            trace_status = "UNSET"

        return TraceData(
            trace_id=trace_id,
            spans=spans,
            start_time=trace_start,
            duration_ms=trace_duration_ms,
            service_name=root_span.service_name,
            root_operation=root_span.operation_name,
            status=trace_status,
        )
