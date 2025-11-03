"""Jaeger backend implementation for querying OpenTelemetry traces."""

import logging
from datetime import datetime
from typing import Any

from openllmetry_mcp.attributes import HealthCheckResponse, SpanAttributes, SpanEvent
from openllmetry_mcp.backends.base import BaseBackend
from openllmetry_mcp.models import SpanData, TraceData, TraceQuery

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

    async def search_traces(self, query: TraceQuery) -> list[TraceData]:
        """Search for traces using Jaeger Query API.

        Args:
            query: Trace query parameters

        Returns:
            List of matching traces

        Raises:
            httpx.HTTPError: If API request fails
        """
        # Jaeger requires a service parameter, so if none specified, query all services
        if not query.service_name:
            logger.debug("No service specified, querying all services")
            services_response = await self.client.get("/api/services")
            services_response.raise_for_status()
            services = services_response.json().get("data", [])

            all_traces = []
            for service in services:
                # Create a new query with the service name
                service_query = TraceQuery(
                    service_name=service,
                    operation_name=query.operation_name,
                    start_time=query.start_time,
                    end_time=query.end_time,
                    min_duration_ms=query.min_duration_ms,
                    max_duration_ms=query.max_duration_ms,
                    tags=query.tags,
                    limit=query.limit,
                    has_error=query.has_error,
                    gen_ai_system=query.gen_ai_system,
                    gen_ai_model=query.gen_ai_model,
                )

                # Query this service
                try:
                    service_traces = await self._search_service_traces(service_query)
                    all_traces.extend(service_traces)
                except Exception as e:
                    logger.warning(f"Failed to query service {service}: {e}")
                    continue

            # Sort by start time and limit
            all_traces.sort(key=lambda t: t.start_time, reverse=True)
            return all_traces[: query.limit]

        # Single service query
        return await self._search_service_traces(query)

    async def _search_service_traces(self, query: TraceQuery) -> list[TraceData]:
        """Search traces for a specific service.

        Args:
            query: Trace query with service_name set

        Returns:
            List of matching traces
        """
        params = query.to_backend_params()

        logger.debug(f"Searching traces with params: {params}")

        response = await self.client.get("/api/traces", params=params)
        response.raise_for_status()

        data = response.json()
        traces = []

        for trace_data in data.get("data", []):
            trace = self._parse_jaeger_trace(trace_data)
            if trace:
                # Apply post-query filters if needed
                if query.has_error is not None:
                    if query.has_error != trace.has_errors:
                        continue
                traces.append(trace)

        return traces

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
        return [op.get("name") for op in data.get("data", []) if op.get("name")]

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

            # Parse all spans
            spans: list[SpanData] = []
            for span_data in spans_data:
                span = self._parse_jaeger_span(span_data)
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

    def _parse_jaeger_span(self, span_data: dict[str, Any]) -> SpanData | None:
        """Parse Jaeger span JSON to SpanData model.

        Args:
            span_data: Raw Jaeger span data

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
            processes = span_data.get("processes", {})
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
