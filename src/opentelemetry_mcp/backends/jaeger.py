"""Jaeger backend implementation for querying OpenTelemetry traces."""

import logging
from datetime import datetime
from typing import Any

from opentelemetry_mcp.attributes import HealthCheckResponse, SpanAttributes, SpanEvent
from opentelemetry_mcp.backends.base import BaseBackend
from opentelemetry_mcp.backends.filter_engine import FilterEngine
from opentelemetry_mcp.models import FilterOperator, SpanData, SpanQuery, TraceData, TraceQuery

logger = logging.getLogger(__name__)


class JaegerBackend(BaseBackend):
    """Jaeger Query API backend implementation."""

    def _create_headers(self) -> dict[str, str]:
        """Create headers for Jaeger API requests.

        Returns:
            Dictionary with optional Bearer token authorization
        """
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def get_supported_operators(self) -> set[FilterOperator]:
        """Get natively supported operators via Jaeger API.

        Jaeger has very limited filtering - only supports equals via tags.
        Most filtering will be done client-side.

        Returns:
            Set of supported FilterOperator values
        """
        return {
            FilterOperator.EQUALS,  # Via tags parameter
        }

    async def search_traces(self, query: TraceQuery) -> list[TraceData]:
        """Search for traces using Jaeger Query API with hybrid filtering.

        Args:
            query: Trace query parameters

        Returns:
            List of matching traces

        Raises:
            ValueError: If service_name is not provided
            httpx.HTTPError: If API request fails
        """
        # Validate service_name is provided
        if not query.service_name:
            raise ValueError(
                "Jaeger backend requires 'service_name' parameter. "
                "Use list_services() to see available services, then specify one with service_name parameter."
            )

        # Get all filters (converted + explicit)
        all_filters = query.get_all_filters()

        # Jaeger only supports service filtering via API (via query.to_backend_params())
        # All other filters must be applied client-side, even if operator is supported
        supported_fields = {"service.name"}  # Only service filtering via API

        native_filters = [
            f
            for f in all_filters
            if f.field in supported_fields and f.operator == FilterOperator.EQUALS
        ]
        client_filters = [f for f in all_filters if f not in native_filters]

        if client_filters:
            logger.info(
                f"Will apply {len(client_filters)} filters client-side: "
                f"{[(f.field, f.operator.value) for f in client_filters]}"
            )

        # Single service query
        return await self._search_service_traces_with_filters(query, native_filters, client_filters)

    async def _search_service_traces_with_filters(
        self,
        query: TraceQuery,
        native_filters: list[Any],
        client_filters: list[Any],
    ) -> list[TraceData]:
        """Search traces for a specific service with hybrid filtering.

        Args:
            query: Trace query with service_name set
            native_filters: Filters that can be pushed to Jaeger
            client_filters: Filters to apply client-side

        Returns:
            List of matching traces
        """
        # Use to_backend_params for now (handles service, operation, duration, time, tags)
        params = query.to_backend_params()

        logger.debug(f"Searching traces with params: {params}")

        response = await self.client.get("/api/traces", params=params)
        response.raise_for_status()

        data = response.json()
        traces = []

        for trace_data in data.get("data", []):
            trace = self._parse_jaeger_trace(trace_data)
            if trace:
                traces.append(trace)

        # Apply client-side filters
        if client_filters:
            traces = FilterEngine.apply_filters(traces, client_filters)

        return traces

    async def search_spans(self, query: SpanQuery) -> list[SpanData]:
        """Search for individual spans using Jaeger Query API.

        Jaeger doesn't have a dedicated spans API, so we search for traces
        and then flatten to get individual spans matching the query.

        Args:
            query: Span query parameters

        Returns:
            List of matching spans (flattened from traces)

        Raises:
            ValueError: If service_name is not provided
            httpx.HTTPError: If API request fails
        """
        # Validate service_name is provided
        if not query.service_name:
            raise ValueError(
                "Jaeger backend requires 'service_name' parameter. "
                "Use list_services() to see available services, then specify one with service_name parameter."
            )

        # Get all filters (converted + explicit)
        all_filters = query.get_all_filters()

        # Jaeger only supports service filtering via API
        supported_fields = {"service.name"}

        native_filters = [
            f
            for f in all_filters
            if f.field in supported_fields and f.operator == FilterOperator.EQUALS
        ]
        client_filters = [f for f in all_filters if f not in native_filters]

        if client_filters:
            logger.info(
                f"Will apply {len(client_filters)} span filters client-side: "
                f"{[(f.field, f.operator.value) for f in client_filters]}"
            )

        # Convert SpanQuery to TraceQuery for Jaeger API
        # We'll fetch more traces than needed and filter spans
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
        traces = await self._search_service_traces_with_filters(
            trace_query,
            native_filters,
            [],  # Don't apply client filters at trace level
        )

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
        """Get a specific trace by ID from Jaeger.

        Args:
            trace_id: Trace identifier

        Returns:
            Complete trace data

        Raises:
            httpx.HTTPError: If trace not found or API request fails
        """
        logger.debug(f"Fetching trace: {trace_id}")

        response = await self.client.get(f"/api/traces/{trace_id}")
        response.raise_for_status()

        data = response.json()

        if not data.get("data") or len(data["data"]) == 0:
            raise ValueError(f"Trace not found: {trace_id}")

        trace = self._parse_jaeger_trace(data["data"][0])
        if not trace:
            raise ValueError(f"Failed to parse trace: {trace_id}")

        return trace

    async def list_services(self) -> list[str]:
        """List all services from Jaeger.

        Returns:
            List of service names

        Raises:
            httpx.HTTPError: If API request fails
        """
        logger.debug("Listing services")

        response = await self.client.get("/api/services")
        response.raise_for_status()

        data = response.json()
        services_raw = data.get("data", [])
        return [str(s) for s in services_raw]

    async def get_service_operations(self, service_name: str) -> list[str]:
        """Get operations for a service from Jaeger.

        Args:
            service_name: Service name

        Returns:
            List of operation names

        Raises:
            httpx.HTTPError: If API request fails
        """
        logger.debug(f"Getting operations for service: {service_name}")

        response = await self.client.get(f"/api/services/{service_name}/operations")
        response.raise_for_status()

        data = response.json()
        return [str(op) for op in data.get("data", [])]

    async def health_check(self) -> HealthCheckResponse:
        """Check Jaeger backend health.

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
                backend="jaeger",
                url=self.url,
                service_count=len(services),
            )
        except Exception as e:
            return HealthCheckResponse(
                status="unhealthy",
                backend="jaeger",
                url=self.url,
                error=str(e),
            )

    def _parse_jaeger_trace(self, trace_data: dict[str, Any]) -> TraceData | None:
        """Parse Jaeger trace JSON format to TraceData model.

        Args:
            trace_data: Raw Jaeger trace data

        Returns:
            Parsed TraceData or None if parsing fails
        """
        try:
            trace_id = trace_data.get("traceID")
            if not trace_id:
                logger.warning("Trace missing traceID")
                return None

            spans_data = trace_data.get("spans", [])
            if not spans_data:
                logger.warning(f"Trace {trace_id} has no spans")
                return None

            # Get processes dictionary from trace level
            processes = trace_data.get("processes", {})

            # Parse all spans
            spans: list[SpanData] = []
            for span_data in spans_data:
                span = self._parse_jaeger_span(span_data, processes)
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
            trace_status = "OK"
            if any(span.has_error for span in spans):
                trace_status = "ERROR"

            return TraceData(
                trace_id=trace_id,
                spans=spans,
                start_time=trace_start,
                duration_ms=trace_duration_ms,
                service_name=root_span.service_name,
                root_operation=root_span.operation_name,
                status=trace_status,  # type: ignore
            )

        except Exception as e:
            logger.error(f"Error parsing trace: {e}")
            return None

    def _parse_jaeger_span(
        self, span_data: dict[str, Any], processes: dict[str, Any]
    ) -> SpanData | None:
        """Parse Jaeger span JSON to SpanData model.

        Args:
            span_data: Raw Jaeger span data
            processes: Process/service mapping from trace level

        Returns:
            Parsed SpanData or None if parsing fails
        """
        try:
            trace_id_raw = span_data.get("traceID")
            span_id_raw = span_data.get("spanID")
            operation_name_raw = span_data.get("operationName")

            if not all([trace_id_raw, span_id_raw, operation_name_raw]):
                logger.warning("Span missing required fields")
                return None

            trace_id = str(trace_id_raw)
            span_id = str(span_id_raw)
            operation_name = str(operation_name_raw)

            # Parse timestamps (Jaeger uses microseconds)
            start_time_us = span_data.get("startTime", 0)
            duration_us = span_data.get("duration", 0)

            start_time = datetime.fromtimestamp(start_time_us / 1_000_000)
            duration_ms = duration_us / 1000

            # Get process/service info
            process_id = span_data.get("processID")
            service_name = "unknown"

            if process_id and process_id in processes:
                service_name = processes[process_id].get("serviceName", "unknown")
            elif "process" in span_data:
                service_name = span_data["process"].get("serviceName", "unknown")

            # Parse references to find parent
            parent_span_id = None
            for ref in span_data.get("references", []):
                if ref.get("refType") == "CHILD_OF":
                    parent_span_id = ref.get("spanID")
                    break

            # Parse tags to attributes dictionary
            attributes_dict: dict[str, Any] = {}
            for tag in span_data.get("tags", []):
                key = tag.get("key")
                value = tag.get("value")
                if key and value is not None:
                    attributes_dict[key] = value

            # Create strongly-typed SpanAttributes
            span_attributes = SpanAttributes(**attributes_dict)

            # Determine span status
            status = "UNSET"
            error_tag = span_attributes.error
            status_code = span_attributes.otel_status_code

            if error_tag is True or status_code == "ERROR":
                status = "ERROR"
            elif status_code == "OK":
                status = "OK"

            # Parse logs/events with strong typing
            events: list[SpanEvent] = []
            for log in span_data.get("logs", []):
                event_attrs: dict[str, str | int | float | bool] = {}
                for field in log.get("fields", []):
                    key = field.get("key")
                    value = field.get("value")
                    if key and value is not None:
                        event_attrs[key] = value

                # Try to identify event name
                event_name = "event"
                if "event" in event_attrs:
                    event_name = str(event_attrs["event"])
                elif "message" in event_attrs:
                    event_name = "log"

                events.append(
                    SpanEvent(
                        name=event_name,
                        timestamp=log.get("timestamp", 0),
                        attributes=event_attrs,
                    )
                )

            return SpanData(
                trace_id=trace_id,
                span_id=span_id,
                parent_span_id=parent_span_id,
                operation_name=operation_name,
                service_name=service_name,
                start_time=start_time,
                duration_ms=duration_ms,
                status=status,  # type: ignore
                attributes=span_attributes,
                events=events,
            )

        except Exception as e:
            logger.error(f"Error parsing span: {e}")
            return None
