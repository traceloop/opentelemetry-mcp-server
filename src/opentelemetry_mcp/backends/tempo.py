"""Grafana Tempo backend implementation with TraceQL support."""

import logging
from datetime import datetime
from typing import Any, Literal

from opentelemetry_mcp.attributes import HealthCheckResponse, SpanAttributes, SpanEvent
from opentelemetry_mcp.backends.base import BaseBackend
from opentelemetry_mcp.backends.filter_engine import FilterEngine
from opentelemetry_mcp.models import (
    Filter,
    FilterOperator,
    FilterType,
    SpanData,
    SpanQuery,
    TraceData,
    TraceQuery,
)

logger = logging.getLogger(__name__)


class TempoBackend(BaseBackend):
    """Grafana Tempo backend with TraceQL query support."""

    def _create_headers(self) -> dict[str, str]:
        """Create headers for Tempo API requests.

        Returns:
            Dictionary with optional Bearer token authorization
        """
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def get_supported_operators(self) -> set[FilterOperator]:
        """Get natively supported operators via TraceQL.

        Tempo's TraceQL supports most operators natively.

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
            FilterOperator.CONTAINS,  # Via regex =~
            FilterOperator.IN,  # Via OR logic
            FilterOperator.EXISTS,  # Via != nil
            FilterOperator.NOT_EXISTS,  # Via = nil
        }

    async def search_traces(self, query: TraceQuery) -> list[TraceData]:
        """Search traces using TraceQL with hybrid filtering.

        Args:
            query: Trace query parameters

        Returns:
            List of matching traces

        Raises:
            httpx.HTTPError: If API request fails
        """
        # Get all filters (converted + explicit)
        all_filters = query.get_all_filters()

        # Separate supported and unsupported filters
        supported_operators = self.get_supported_operators()
        native_filters = [f for f in all_filters if f.operator in supported_operators]
        client_filters = [f for f in all_filters if f.operator not in supported_operators]

        if client_filters:
            logger.info(
                f"Will apply {len(client_filters)} filters client-side: "
                f"{[f.operator.value for f in client_filters]}"
            )

        # Build TraceQL query from native filters
        traceql = self._build_traceql_from_filters(native_filters, query)
        logger.debug(f"Executing TraceQL: {traceql}")

        params: dict[str, str | int] = {"q": traceql, "limit": query.limit}

        # Tempo requires time range - default to last 24 hours if not specified
        if query.start_time:
            params["start"] = int(query.start_time.timestamp())
        else:
            from datetime import timedelta

            params["start"] = int((datetime.now() - timedelta(days=1)).timestamp())

        if query.end_time:
            params["end"] = int(query.end_time.timestamp())
        else:
            from datetime import timedelta

            params["end"] = int((datetime.now() + timedelta(hours=1)).timestamp())

        response = await self.client.get("/api/search", params=params)
        response.raise_for_status()

        data = response.json()
        traces = []

        # Tempo search returns an array of trace results directly
        # WARNING: Each trace requires a separate HTTP request, so limit to avoid performance issues
        trace_results = data if isinstance(data, list) else data.get("traces", [])
        max_traces_to_fetch = min(len(trace_results), 50)  # Cap at 50 to avoid too many requests

        if len(trace_results) > max_traces_to_fetch:
            logger.warning(
                f"Limiting trace fetch to {max_traces_to_fetch} out of {len(trace_results)} "
                f"results to avoid excessive API calls"
            )

        for trace_result in trace_results[:max_traces_to_fetch]:
            trace_id = trace_result.get("traceID")
            if trace_id:
                try:
                    trace_response = await self.client.get(f"/api/traces/{trace_id}")
                    trace_response.raise_for_status()
                    trace_data = trace_response.json()
                    trace = self._parse_tempo_trace(trace_data, trace_id_hex=trace_id)
                    if trace:
                        traces.append(trace)
                except Exception as e:
                    logger.warning(f"Failed to fetch trace {trace_id}: {e}")

        # Apply client-side filters
        if client_filters:
            traces = FilterEngine.apply_filters(traces, client_filters)

        return traces

    async def search_spans(self, query: SpanQuery) -> list[SpanData]:
        """Search for individual spans using TraceQL with hybrid filtering.

        Tempo doesn't have a dedicated spans API, so we search for traces
        and then flatten to get individual spans matching the query.

        Args:
            query: Span query parameters

        Returns:
            List of matching spans (flattened from traces)

        Raises:
            httpx.HTTPError: If API request fails
        """
        # Get all filters (converted + explicit)
        all_filters = query.get_all_filters()

        # For span queries, we need to be careful about which filters to push to TraceQL
        # TraceQL works at the trace level, so span-level filters will match traces that
        # have AT LEAST ONE span matching the condition, then return ALL spans from those traces.
        # Therefore, span attribute filters should be applied client-side.

        # Filters that can be pushed to TraceQL for span search:
        # - service.name (trace-level)
        # - duration (can filter traces by duration)
        # - status (can filter traces by status)

        # Filters that MUST be applied client-side:
        # - Span attributes (gen_ai.*, http.*, etc.) - would match entire trace
        # - operation_name - would match trace if ANY span has that operation

        trace_level_fields = {"service.name", "duration", "duration_ms", "status"}

        supported_operators = self.get_supported_operators()
        native_filters = [
            f
            for f in all_filters
            if f.operator in supported_operators and f.field in trace_level_fields
        ]
        client_filters = [f for f in all_filters if f not in native_filters]

        if client_filters:
            logger.info(
                f"Will apply {len(client_filters)} span filters client-side: "
                f"{[(f.field, f.operator.value) for f in client_filters]}"
            )

        # Build TraceQL query from native filters
        # Convert SpanQuery to TraceQuery for TraceQL building
        trace_query = TraceQuery(
            service_name=query.service_name,
            operation_name=query.operation_name,
            start_time=query.start_time,
            end_time=query.end_time,
            min_duration_ms=query.min_duration_ms,
            max_duration_ms=query.max_duration_ms,
            tags=query.tags,
            limit=query.limit * 2,  # Fetch more traces to ensure we get enough spans
            has_error=query.has_error,
            gen_ai_system=query.gen_ai_system,
            gen_ai_request_model=query.gen_ai_request_model,
            gen_ai_response_model=query.gen_ai_response_model,
            filters=query.filters,
        )

        traceql = self._build_traceql_from_filters(native_filters, trace_query)
        logger.debug(f"Executing TraceQL for spans: {traceql}")

        params: dict[str, str | int] = {"q": traceql, "limit": trace_query.limit}

        # Tempo requires time range - default to last 24 hours if not specified
        if query.start_time:
            params["start"] = int(query.start_time.timestamp())
        else:
            from datetime import timedelta

            params["start"] = int((datetime.now() - timedelta(days=1)).timestamp())

        if query.end_time:
            params["end"] = int(query.end_time.timestamp())
        else:
            from datetime import timedelta

            params["end"] = int((datetime.now() + timedelta(hours=1)).timestamp())

        response = await self.client.get("/api/search", params=params)
        response.raise_for_status()

        data = response.json()

        # Fetch traces and flatten spans
        trace_results = data if isinstance(data, list) else data.get("traces", [])
        max_traces_to_fetch = min(len(trace_results), 50)  # Cap at 50 to avoid too many requests

        if len(trace_results) > max_traces_to_fetch:
            logger.warning(
                f"Limiting trace fetch to {max_traces_to_fetch} out of {len(trace_results)} "
                f"results to avoid excessive API calls"
            )

        all_spans: list[SpanData] = []
        for trace_result in trace_results[:max_traces_to_fetch]:
            trace_id = trace_result.get("traceID")
            if trace_id:
                try:
                    trace_response = await self.client.get(f"/api/traces/{trace_id}")
                    trace_response.raise_for_status()
                    trace_data = trace_response.json()
                    trace = self._parse_tempo_trace(trace_data, trace_id_hex=trace_id)
                    if trace:
                        all_spans.extend(trace.spans)
                except Exception as e:
                    logger.warning(f"Failed to fetch trace {trace_id}: {e}")

        # Apply client-side filters to spans
        if client_filters:
            all_spans = FilterEngine.apply_filters(all_spans, client_filters)

        # Limit the number of spans returned
        return all_spans[: query.limit]

    async def get_trace(self, trace_id: str) -> TraceData:
        """Get a specific trace by ID from Tempo."""
        response = await self.client.get(f"/api/traces/{trace_id}")
        response.raise_for_status()
        data = response.json()
        # Pass trace_id_hex to ensure consistent trace ID format (hex instead of base64)
        trace = self._parse_tempo_trace(data, trace_id_hex=trace_id)
        if not trace:
            raise ValueError(f"Failed to parse trace {trace_id}")
        return trace

    async def list_services(self) -> list[str]:
        """List all services from Tempo.

        Uses search results to extract unique service names since the tag values
        endpoint may not be available on all Tempo instances.

        Returns:
            List of service names

        Raises:
            httpx.HTTPError: If API request fails
        """
        logger.debug("Listing services")

        # Use TraceQL to search all traces and extract unique services
        traceql = "{}"  # Match all traces
        params: dict[str, str | int] = {"q": traceql, "limit": 1000}

        # Add default time range (last 24 hours)
        from datetime import timedelta

        params["start"] = int((datetime.now() - timedelta(days=1)).timestamp())
        params["end"] = int((datetime.now() + timedelta(hours=1)).timestamp())

        response = await self.client.get("/api/search", params=params)
        response.raise_for_status()

        data = response.json()
        trace_results = data if isinstance(data, list) else data.get("traces", [])

        # Extract unique service names
        services_set = set()
        for trace_result in trace_results:
            service_name = trace_result.get("rootServiceName")
            if service_name:
                services_set.add(service_name)

        services = sorted(list(services_set))
        logger.debug(f"Found {len(services)} unique services from {len(trace_results)} traces")
        return services

    async def get_service_operations(self, service_name: str) -> list[str]:
        """Get operations for a service from Tempo.

        Args:
            service_name: Service name

        Returns:
            List of operation names

        Raises:
            httpx.HTTPError: If API request fails
        """
        logger.debug(f"Getting operations for service: {service_name}")

        # Use TraceQL to find operations
        traceql = f'{{ resource.service.name = "{service_name}" }}'
        params: dict[str, str | int] = {"q": traceql, "limit": 100}

        response = await self.client.get("/api/search", params=params)
        response.raise_for_status()

        data = response.json()

        # Extract unique operation names
        operations = set()
        trace_results = data if isinstance(data, list) else data.get("traces", [])
        for trace_result in trace_results:
            if "rootServiceName" in trace_result:
                operations.add(trace_result.get("rootTraceName", ""))

        return list(operations)

    async def health_check(self) -> HealthCheckResponse:
        """Check Tempo backend health.

        Returns:
            Health status information
        """
        logger.debug("Checking backend health")

        try:
            # Try a simple search as a health check
            params: dict[str, str | int] = {"q": "{}", "limit": 1}
            response = await self.client.get("/api/search", params=params)
            response.raise_for_status()

            return HealthCheckResponse(
                status="healthy",
                backend="tempo",
                url=self.url,
            )
        except Exception as e:
            return HealthCheckResponse(
                status="unhealthy",
                backend="tempo",
                url=self.url,
                error=str(e),
            )

    def _build_traceql_from_filters(self, filters: list[Filter], query: TraceQuery) -> str:
        """Build TraceQL query from Filter objects.

        Args:
            filters: List of Filter conditions
            query: Original query (for time range)

        Returns:
            TraceQL query string
        """
        conditions = []

        for filter_obj in filters:
            condition = self._filter_to_traceql(filter_obj)
            if condition:
                conditions.append(condition)

        # If no filters, match all traces
        if not conditions:
            return "{}"

        # Combine with AND logic
        return "{ " + " && ".join(conditions) + " }"

    def _filter_to_traceql(self, filter_obj: Filter) -> str | None:
        """Convert a single Filter to TraceQL condition.

        Args:
            filter_obj: Filter to convert

        Returns:
            TraceQL condition string or None if not supported
        """
        field = filter_obj.field
        operator = filter_obj.operator
        value = filter_obj.value
        values = filter_obj.values

        # Map field names to TraceQL syntax
        if field == "service.name":
            traceql_field = "resource.service.name"
        elif field == "name" or field == "operation_name":
            traceql_field = "name"
        elif field == "duration":
            traceql_field = "duration"
        elif field == "status":
            # Special handling for status
            if operator == FilterOperator.EQUALS:
                if value == "ERROR":
                    return "status = error"
                elif value == "OK":
                    return "status = ok"
            return None
        else:
            # Assume it's a span attribute
            traceql_field = f"span.{field}"

        # Build condition based on operator
        if operator == FilterOperator.EQUALS:
            if filter_obj.value_type == FilterType.STRING:
                return f'{traceql_field} = "{value}"'
            else:
                return f"{traceql_field} = {value}"

        elif operator == FilterOperator.NOT_EQUALS:
            if filter_obj.value_type == FilterType.STRING:
                return f'{traceql_field} != "{value}"'
            else:
                return f"{traceql_field} != {value}"

        elif operator == FilterOperator.GT:
            if field == "duration":
                return f"{traceql_field} > {value}ms"
            return f"{traceql_field} > {value}"

        elif operator == FilterOperator.LT:
            if field == "duration":
                return f"{traceql_field} < {value}ms"
            return f"{traceql_field} < {value}"

        elif operator == FilterOperator.GTE:
            if field == "duration":
                return f"{traceql_field} >= {value}ms"
            return f"{traceql_field} >= {value}"

        elif operator == FilterOperator.LTE:
            if field == "duration":
                return f"{traceql_field} <= {value}ms"
            return f"{traceql_field} <= {value}"

        elif operator == FilterOperator.CONTAINS:
            # Use regex for contains
            return f'{traceql_field} =~ ".*{value}.*"'

        elif operator == FilterOperator.IN:
            # Build OR condition
            if not values:
                return None
            if filter_obj.value_type == FilterType.STRING:
                or_conditions = [f'{traceql_field} = "{v}"' for v in values]
            else:
                or_conditions = [f"{traceql_field} = {v}" for v in values]
            return "(" + " || ".join(or_conditions) + ")"

        elif operator == FilterOperator.EXISTS:
            return f"{traceql_field} != nil"

        elif operator == FilterOperator.NOT_EXISTS:
            return f"{traceql_field} = nil"

        logger.warning(f"Unsupported operator for TraceQL: {operator}")
        return None

    def _build_traceql_query(self, query: TraceQuery) -> str:
        """Build TraceQL query from query parameters.

        This method is kept for backward compatibility. New code should use
        _build_traceql_from_filters with query.get_all_filters().

        Args:
            query: Trace query parameters

        Returns:
            TraceQL query string
        """
        # Convert to filters and delegate
        filters = query.get_all_filters()
        if not filters:
            # Empty query - match all traces
            return "{}"
        return self._build_traceql_from_filters(filters, query)

    def _parse_tempo_trace(
        self, trace_data: dict[str, Any], trace_id_hex: str | None = None
    ) -> TraceData | None:
        """Parse Tempo trace format to TraceData.

        Tempo returns OTLP JSON format, which is different from Jaeger.

        Args:
            trace_data: Raw Tempo trace data
            trace_id_hex: Optional hex trace ID from search API (preferred over OTLP base64)

        Returns:
            Parsed TraceData or None
        """
        try:
            # Tempo returns OTLP format with batches
            batches = trace_data.get("batches", [])
            if not batches:
                logger.warning("No batches in trace")
                return None

            all_spans = []
            trace_id = trace_id_hex  # Use hex format if provided

            for batch in batches:
                resource = batch.get("resource", {})
                resource_attrs = self._parse_otlp_attributes(resource.get("attributes", []))
                service_name = resource_attrs.get("service.name", "unknown")

                for scope_span in batch.get("scopeSpans", []):
                    for span_data in scope_span.get("spans", []):
                        span = self._parse_otlp_span(span_data, str(service_name))
                        if span:
                            all_spans.append(span)
                            # Only use OTLP trace_id as fallback if hex not provided
                            if not trace_id:
                                trace_id = span.trace_id

            if not all_spans or not trace_id:
                logger.warning("No valid spans found")
                return None

            # Find root span
            root_spans = [s for s in all_spans if not s.parent_span_id]
            root_span = root_spans[0] if root_spans else all_spans[0]

            # Calculate trace duration
            start_times = [s.start_time for s in all_spans]
            end_times = [
                datetime.fromtimestamp(
                    s.start_time.timestamp() + (s.duration_ms / 1000), tz=s.start_time.tzinfo
                )
                for s in all_spans
            ]
            trace_start = min(start_times)
            trace_end = max(end_times)
            trace_duration_ms = (trace_end - trace_start).total_seconds() * 1000

            # Determine status
            trace_status: Literal["OK", "ERROR", "UNSET"] = "OK"
            if any(span.has_error for span in all_spans):
                trace_status = "ERROR"

            return TraceData(
                trace_id=trace_id,
                spans=all_spans,
                start_time=trace_start,
                duration_ms=trace_duration_ms,
                service_name=root_span.service_name,
                root_operation=root_span.operation_name,
                status=trace_status,
            )

        except Exception as e:
            logger.error(f"Error parsing Tempo trace: {e}")
            return None

    def _parse_otlp_span(self, span_data: dict[str, Any], service_name: str) -> SpanData | None:
        """Parse OTLP span format.

        Args:
            span_data: Raw OTLP span
            service_name: Service name from resource

        Returns:
            Parsed SpanData or None
        """
        try:
            trace_id_raw = span_data.get("traceId")
            span_id_raw = span_data.get("spanId")
            name_raw = span_data.get("name")

            if not all([trace_id_raw, span_id_raw, name_raw]):
                return None

            trace_id = str(trace_id_raw)
            span_id = str(span_id_raw)
            name = str(name_raw)

            # Parse timestamps (OTLP uses nanoseconds)
            start_time_ns = int(span_data.get("startTimeUnixNano", 0))
            end_time_ns = int(span_data.get("endTimeUnixNano", 0))

            start_time = datetime.fromtimestamp(start_time_ns / 1_000_000_000)
            duration_ns = end_time_ns - start_time_ns
            duration_ms = duration_ns / 1_000_000

            # Parent span ID
            parent_span_id = span_data.get("parentSpanId")

            # Parse attributes and create strongly-typed SpanAttributes
            attributes_dict = self._parse_otlp_attributes(span_data.get("attributes", []))
            span_attributes = SpanAttributes(**attributes_dict)  # type: ignore[arg-type]

            # Parse status
            status_data = span_data.get("status", {})
            status_code = status_data.get("code")
            status: Literal["OK", "ERROR", "UNSET"] = "UNSET"

            # Handle both string enum and numeric formats
            if isinstance(status_code, str):
                if "OK" in status_code:
                    status = "OK"
                elif "ERROR" in status_code:
                    status = "ERROR"
            elif isinstance(status_code, int):
                if status_code == 1:
                    status = "OK"
                elif status_code == 2:
                    status = "ERROR"

            # Parse events with strong typing
            events: list[SpanEvent] = []
            for event_data in span_data.get("events", []):
                event_attrs = self._parse_otlp_attributes(event_data.get("attributes", []))
                events.append(
                    SpanEvent(
                        name=event_data.get("name", "event"),
                        timestamp=event_data.get("timeUnixNano", 0),
                        attributes=event_attrs,
                    )
                )

            return SpanData(
                trace_id=trace_id,
                span_id=span_id,
                parent_span_id=parent_span_id if parent_span_id else None,
                operation_name=name,
                service_name=service_name,
                start_time=start_time,
                duration_ms=duration_ms,
                status=status,
                attributes=span_attributes,
                events=events,
            )

        except Exception as e:
            logger.error(f"Error parsing OTLP span: {e}")
            return None

    def _parse_otlp_attributes(
        self, attributes: list[dict[str, Any]]
    ) -> dict[str, str | int | float | bool]:
        """Parse OTLP attribute format.

        OTLP attributes have structure: {"key": "name", "value": {"stringValue": "..."}}

        Args:
            attributes: List of OTLP attributes

        Returns:
            Dictionary of parsed attributes with typed values
        """
        result: dict[str, str | int | float | bool] = {}
        for attr in attributes:
            key = attr.get("key")
            if not key:
                continue

            value_obj = attr.get("value", {})

            # OTLP values can be different types
            if "stringValue" in value_obj:
                result[key] = value_obj["stringValue"]
            elif "intValue" in value_obj:
                result[key] = int(value_obj["intValue"])
            elif "doubleValue" in value_obj:
                result[key] = float(value_obj["doubleValue"])
            elif "boolValue" in value_obj:
                result[key] = value_obj["boolValue"]
            elif "arrayValue" in value_obj:
                # Simplified array handling - convert to string
                result[key] = str(value_obj["arrayValue"])

        return result
