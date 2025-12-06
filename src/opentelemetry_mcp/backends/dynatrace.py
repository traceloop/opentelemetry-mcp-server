"""Dynatrace backend implementation for querying OpenTelemetry traces."""

import logging
from datetime import datetime, timedelta
from typing import Any, Literal

from opentelemetry_mcp.attributes import HealthCheckResponse, SpanAttributes, SpanEvent
from opentelemetry_mcp.backends.base import BaseBackend
from opentelemetry_mcp.backends.filter_engine import FilterEngine
from opentelemetry_mcp.models import (
    FilterOperator,
    SpanData,
    SpanQuery,
    TraceData,
    TraceQuery,
)

logger = logging.getLogger(__name__)


class DynatraceBackend(BaseBackend):
    """Dynatrace API backend implementation for OpenTelemetry traces.

    Uses Dynatrace Trace API v2 and Distributed Traces API to query traces.
    Supports OpenLLMetry semantic conventions (gen_ai.* attributes).
    """

    def _create_headers(self) -> dict[str, str]:
        """Create headers for Dynatrace API requests.

        Returns:
            Dictionary with Bearer token authorization
        """
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Api-Token {self.api_key}"
        return headers

    def get_supported_operators(self) -> set[FilterOperator]:
        """Get natively supported operators via Dynatrace API.

        Dynatrace Trace API supports basic filtering via query parameters.
        Most advanced filtering will be done client-side.

        Returns:
            Set of supported FilterOperator values
        """
        return {
            FilterOperator.EQUALS,  # Via query parameters
        }

    async def search_traces(self, query: TraceQuery) -> list[TraceData]:
        """Search for traces using Dynatrace Trace API v2.

        Args:
            query: Trace query parameters

        Returns:
            List of matching traces

        Raises:
            httpx.HTTPError: If API request fails
        """
        logger.debug(f"Searching traces with query: {query}")

        # Get all filters
        all_filters = query.get_all_filters()

        # Dynatrace API supports limited filtering via query parameters
        # Most filters will be applied client-side
        supported_fields = {"service.name"}  # Service filtering via API
        supported_operators = self.get_supported_operators()

        native_filters = [
            f
            for f in all_filters
            if f.field in supported_fields and f.operator in supported_operators
        ]
        client_filters = [f for f in all_filters if f not in native_filters]

        if client_filters:
            logger.info(
                f"Will apply {len(client_filters)} filters client-side: "
                f"{[(f.field, f.operator.value) for f in client_filters]}"
            )

        # Build query parameters
        params: dict[str, Any] = {
            "limit": query.limit,
        }

        # Add time range (Dynatrace uses milliseconds since epoch)
        if query.start_time:
            params["from"] = int(query.start_time.timestamp() * 1000)
        else:
            # Default to last 24 hours if not specified
            params["from"] = int((datetime.now() - timedelta(days=1)).timestamp() * 1000)

        if query.end_time:
            params["to"] = int(query.end_time.timestamp() * 1000)
        else:
            params["to"] = int(datetime.now().timestamp() * 1000)

        # Add service filter if available
        if query.service_name:
            params["service"] = query.service_name

        # Add operation filter if available
        if query.operation_name:
            params["operation"] = query.operation_name

        # Add duration filters
        if query.min_duration_ms:
            params["minDuration"] = query.min_duration_ms
        if query.max_duration_ms:
            params["maxDuration"] = query.max_duration_ms

        # Add error filter
        if query.has_error is not None:
            params["error"] = query.has_error

        logger.debug(f"Querying Dynatrace API with params: {params}")

        # Query Dynatrace Trace API v2
        # Endpoint: /api/v2/traces
        response = await self.client.get("/api/v2/traces", params=params)
        response.raise_for_status()

        data = response.json()
        traces = []

        # Parse trace results
        trace_results = data.get("traces", []) if isinstance(data, dict) else data

        # Limit the number of traces to fetch details for
        max_traces_to_fetch = min(len(trace_results), 50)

        if len(trace_results) > max_traces_to_fetch:
            logger.warning(
                f"Limiting trace fetch to {max_traces_to_fetch} out of {len(trace_results)} "
                f"results to avoid excessive API calls"
            )

        for trace_result in trace_results[:max_traces_to_fetch]:
            trace_id = trace_result.get("traceId") or trace_result.get("trace_id")
            if trace_id:
                try:
                    # Fetch full trace details
                    trace = await self.get_trace(str(trace_id))
                    if trace:
                        traces.append(trace)
                except Exception as e:
                    logger.warning(f"Failed to fetch trace {trace_id}: {e}")

        # Apply client-side filters
        if client_filters:
            traces = FilterEngine.apply_filters(traces, client_filters)

        return traces

    async def search_spans(self, query: SpanQuery) -> list[SpanData]:
        """Search for individual spans using Dynatrace API.

        Dynatrace doesn't have a dedicated spans API, so we search for traces
        and then flatten to get individual spans matching the query.

        Args:
            query: Span query parameters

        Returns:
            List of matching spans (flattened from traces)

        Raises:
            httpx.HTTPError: If API request fails
        """
        logger.debug(f"Searching spans with query: {query}")

        # Get all filters
        all_filters = query.get_all_filters()

        # For span queries, most filtering will be client-side
        supported_fields = {"service.name"}
        supported_operators = self.get_supported_operators()

        native_filters = [
            f
            for f in all_filters
            if f.field in supported_fields and f.operator in supported_operators
        ]
        client_filters = [f for f in all_filters if f not in native_filters]

        if client_filters:
            logger.info(
                f"Will apply {len(client_filters)} span filters client-side: "
                f"{[(f.field, f.operator.value) for f in client_filters]}"
            )

        # Convert SpanQuery to TraceQuery for Dynatrace API
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

        # Search traces
        traces = await self.search_traces(trace_query)

        # Flatten spans from all traces
        all_spans: list[SpanData] = []
        for trace in traces:
            all_spans.extend(trace.spans)

        # Apply client-side filters to spans
        if client_filters:
            all_spans = FilterEngine.apply_filters(all_spans, client_filters)

        # Limit the number of spans returned
        return all_spans[: query.limit]

    async def get_trace(self, trace_id: str) -> TraceData:
        """Get a specific trace by ID from Dynatrace.

        Args:
            trace_id: Trace identifier

        Returns:
            Complete trace data with all spans

        Raises:
            httpx.HTTPError: If trace not found or API request fails
        """
        logger.debug(f"Fetching trace: {trace_id}")

        # Query Dynatrace Distributed Traces API
        # Endpoint: /api/v2/traces/{traceId}
        response = await self.client.get(f"/api/v2/traces/{trace_id}")
        response.raise_for_status()

        data = response.json()

        # Parse trace data
        trace = self._parse_dynatrace_trace(data, trace_id)
        if not trace:
            raise ValueError(f"Failed to parse trace: {trace_id}")

        return trace

    async def list_services(self) -> list[str]:
        """List all available services from Dynatrace.

        Uses the services endpoint or extracts from trace search results.

        Returns:
            List of service names

        Raises:
            httpx.HTTPError: If API request fails
        """
        logger.debug("Listing services")

        try:
            # Try to use the services endpoint if available
            response = await self.client.get("/api/v2/services")
            response.raise_for_status()
            data = response.json()

            services = []
            if isinstance(data, list):
                services = [str(s.get("name", s)) for s in data if s]
            elif isinstance(data, dict):
                services_data = data.get("services", []) or data.get("data", [])
                services = [str(s.get("name", s)) for s in services_data if s]

            if services:
                return sorted(list(set(services)))
        except Exception as e:
            logger.debug(f"Services endpoint not available, using trace search: {e}")

        # Fallback: Extract services from trace search
        # Search for traces in the last 24 hours to discover services

        params = {
            "from": int((datetime.now() - timedelta(days=1)).timestamp() * 1000),
            "to": int(datetime.now().timestamp() * 1000),
            "limit": 1000,
        }

        response = await self.client.get("/api/v2/traces", params=params)
        response.raise_for_status()

        data = response.json()
        trace_results = data.get("traces", []) if isinstance(data, dict) else data

        services_set = set()
        for trace_result in trace_results:
            service_name = trace_result.get("serviceName") or trace_result.get("service")
            if service_name:
                services_set.add(str(service_name))

        services = sorted(list(services_set))
        logger.debug(f"Found {len(services)} unique services from {len(trace_results)} traces")
        return services

    async def get_service_operations(self, service_name: str) -> list[str]:
        """Get all operations for a specific service.

        Args:
            service_name: Service name

        Returns:
            List of operation names

        Raises:
            httpx.HTTPError: If query fails
        """
        logger.debug(f"Getting operations for service: {service_name}")

        # Search for traces from this service to discover operations

        params = {
            "service": service_name,
            "from": int((datetime.now() - timedelta(days=1)).timestamp() * 1000),
            "to": int(datetime.now().timestamp() * 1000),
            "limit": 1000,
        }

        response = await self.client.get("/api/v2/traces", params=params)
        response.raise_for_status()

        data = response.json()
        trace_results = data.get("traces", []) if isinstance(data, dict) else data

        operations = set()
        for trace_result in trace_results:
            operation_name = trace_result.get("operationName") or trace_result.get("operation")
            if operation_name:
                operations.add(str(operation_name))

        return sorted(list(operations))

    async def health_check(self) -> HealthCheckResponse:
        """Check Dynatrace backend health.

        Returns:
            Health status information

        Raises:
            httpx.HTTPError: If backend is unreachable
        """
        logger.debug("Checking backend health")

        try:
            # Try to list services as a health check
            services = await self.list_services()
            return HealthCheckResponse(
                status="healthy",
                backend="dynatrace",
                url=self.url,
                service_count=len(services),
            )
        except Exception as e:
            return HealthCheckResponse(
                status="unhealthy",
                backend="dynatrace",
                url=self.url,
                error=str(e),
            )

    def _parse_dynatrace_trace(
        self, trace_data: dict[str, Any], trace_id: str
    ) -> TraceData | None:
        """Parse Dynatrace trace format to TraceData.

        Args:
            trace_data: Raw Dynatrace trace data
            trace_id: Trace identifier

        Returns:
            Parsed TraceData or None if parsing fails
        """
        try:
            # Dynatrace may return traces in different formats
            # Handle both single trace and trace with spans
            spans_data = trace_data.get("spans", [])
            if not spans_data:
                # Try alternative format
                spans_data = trace_data.get("data", {}).get("spans", [])

            if not spans_data:
                logger.warning(f"Trace {trace_id} has no spans")
                return None

            # Parse all spans
            spans: list[SpanData] = []
            for span_data in spans_data:
                span = self._parse_dynatrace_span(span_data, trace_id)
                if span:
                    spans.append(span)

            if not spans:
                logger.warning(f"No valid spans in trace {trace_id}")
                return None

            # Find root span (no parent)
            root_spans = [s for s in spans if not s.parent_span_id]
            root_span = root_spans[0] if root_spans else spans[0]

            # Calculate trace duration
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

            # Determine overall status (ERROR if any span has error)
            trace_status: Literal["OK", "ERROR", "UNSET"] = "OK"
            if any(span.has_error for span in spans):
                trace_status = "ERROR"

            return TraceData(
                trace_id=trace_id,
                spans=spans,
                start_time=trace_start,
                duration_ms=trace_duration_ms,
                service_name=root_span.service_name,
                root_operation=root_span.operation_name,
                status=trace_status,
            )

        except Exception as e:
            logger.error(f"Error parsing trace: {e}")
            return None

    def _parse_dynatrace_span(
        self, span_data: dict[str, Any], trace_id: str
    ) -> SpanData | None:
        """Parse Dynatrace span format to SpanData.

        Args:
            span_data: Raw Dynatrace span data
            trace_id: Trace identifier

        Returns:
            Parsed SpanData or None if parsing fails
        """
        try:
            span_id_raw = span_data.get("spanId") or span_data.get("span_id")
            operation_name_raw = span_data.get("operationName") or span_data.get("name")

            if not all([span_id_raw, operation_name_raw]):
                logger.warning("Span missing required fields")
                return None

            span_id = str(span_id_raw)
            operation_name = str(operation_name_raw)

            # Parse timestamps (Dynatrace uses milliseconds since epoch)
            start_time_ms = span_data.get("startTime", span_data.get("start_time", 0))
            if isinstance(start_time_ms, str):
                # Try to parse ISO format
                try:
                    start_time = datetime.fromisoformat(start_time_ms.replace("Z", "+00:00"))
                except Exception:
                    start_time = datetime.fromtimestamp(int(start_time_ms) / 1000)
            else:
                start_time = datetime.fromtimestamp(start_time_ms / 1000)

            duration_ms = span_data.get("duration", span_data.get("duration_ms", 0))
            if isinstance(duration_ms, str):
                duration_ms = float(duration_ms)

            # Get service name
            service_name = (
                span_data.get("serviceName")
                or span_data.get("service")
                or span_data.get("service_name", "unknown")
            )

            # Get parent span ID
            parent_span_id = span_data.get("parentSpanId") or span_data.get("parent_span_id")
            if parent_span_id:
                parent_span_id = str(parent_span_id)

            # Parse attributes
            attributes_dict: dict[str, Any] = {}
            if "attributes" in span_data:
                attrs = span_data["attributes"]
                if isinstance(attrs, dict):
                    attributes_dict.update(attrs)
                elif isinstance(attrs, list):
                    # Handle list of key-value pairs
                    for attr in attrs:
                        if isinstance(attr, dict):
                            key = attr.get("key")
                            value = attr.get("value")
                            if key:
                                attributes_dict[key] = value

            # Also check for tags (alternative format)
            if "tags" in span_data:
                tags = span_data["tags"]
                if isinstance(tags, dict):
                    attributes_dict.update(tags)

            # Create strongly-typed SpanAttributes
            span_attributes = SpanAttributes(**attributes_dict)

            # Determine span status
            status: Literal["OK", "ERROR", "UNSET"] = "UNSET"
            error_tag = span_attributes.error
            status_code = span_attributes.otel_status_code

            # Check for error indicators
            if error_tag is True or status_code == "ERROR":
                status = "ERROR"
            elif status_code == "OK":
                status = "OK"
            elif span_data.get("error", False):
                status = "ERROR"

            # Parse events/logs
            events: list[SpanEvent] = []
            for event_data in span_data.get("events", span_data.get("logs", [])):
                event_attrs: dict[str, str | int | float | bool] = {}
                if isinstance(event_data, dict):
                    if "attributes" in event_data:
                        event_attrs.update(event_data["attributes"])
                    elif "fields" in event_data:
                        # Handle Jaeger-style fields
                        for field in event_data["fields"]:
                            if isinstance(field, dict):
                                key = field.get("key")
                                value = field.get("value")
                                if key:
                                    event_attrs[key] = value

                event_name = event_data.get("name", "event") if isinstance(event_data, dict) else "event"
                event_timestamp = (
                    event_data.get("timestamp", 0) if isinstance(event_data, dict) else 0
                )

                events.append(
                    SpanEvent(
                        name=event_name,
                        timestamp=event_timestamp,
                        attributes=event_attrs,
                    )
                )

            return SpanData(
                trace_id=trace_id,
                span_id=span_id,
                parent_span_id=parent_span_id,
                operation_name=operation_name,
                service_name=str(service_name),
                start_time=start_time,
                duration_ms=duration_ms,
                status=status,
                attributes=span_attributes,
                events=events,
            )

        except Exception as e:
            logger.error(f"Error parsing span: {e}")
            return None

