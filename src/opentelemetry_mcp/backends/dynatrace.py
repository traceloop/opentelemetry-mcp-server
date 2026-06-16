import logging
from datetime import datetime
from typing import Any

from opentelemetry_mcp.attributes import HealthCheckResponse, SpanAttributes, SpanEvent
from opentelemetry_mcp.backends.base import BaseBackend
from opentelemetry_mcp.backends.filter_engine import FilterEngine
from opentelemetry_mcp.models import FilterOperator, SpanData, SpanQuery, TraceData, TraceQuery

logger = logging.getLogger(__name__)


class DynatraceBackend(BaseBackend):
    """Dynatrace v2 Trace API backend implementation."""

    def _create_headers(self) -> dict[str, str]:
        """Create headers for Dynatrace API requests using Bearer authentication."""
        headers = {
            "Content-Type": "application/json",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def get_supported_operators(self) -> set[FilterOperator]:
        """Get natively supported filter operators via Dynatrace API."""
        return {
            FilterOperator.EQUALS,
        }

    async def search_traces(self, query: TraceQuery) -> list[TraceData]:
        """Search for traces using Dynatrace Trace API."""
        # Use backend parameters for filtering criteria
        params = query.to_backend_params()
        logger.debug(f"Searching Dynatrace traces with params: {params}")

        # Querying Dynatrace Trace API v2 endpoint
        response = await self.client.get("/api/v2/traces", params=params)
        response.raise_for_status()

        data = response.json()
        traces = []

        for trace_data in data.get("traces", []):
            trace = self._parse_dynatrace_trace(trace_data)
            if trace:
                traces.append(trace)

        return traces

    async def search_spans(self, query: SpanQuery) -> list[SpanData]:
        """Search for individual spans and flatten them from traces."""
        # Flattening strategy matching the repository pattern
        trace_query = TraceQuery(
            service_name=query.service_name,
            operation_name=query.operation_name,
            start_time=query.start_time,
            end_time=query.end_time,
            limit=query.limit * 2,
        )

        traces = await self.search_traces(trace_query)
        all_spans: list[SpanData] = []
        for trace in traces:
            all_spans.extend(trace.spans)

        return all_spans[: query.limit]

    async def get_trace(self, trace_id: str) -> TraceData:
        """Get a specific trace by its ID from Dynatrace."""
        logger.debug(f"Fetching Dynatrace trace: {trace_id}")

        response = await self.client.get(f"/api/v2/traces/{trace_id}")
        response.raise_for_status()

        data = response.json()
        if not data:
            raise ValueError(f"Trace not found: {trace_id}")

        trace = self._parse_dynatrace_trace(data)
        if not trace:
            raise ValueError(f"Failed to parse Dynatrace trace: {trace_id}")

        return trace

    async def list_services(self) -> list[str]:
        """List all available service names from Dynatrace."""
        logger.debug("Listing Dynatrace services")

        response = await self.client.get("/api/v2/traces/services")
        response.raise_for_status()

        data = response.json()
        return [str(s) for s in data.get("services", [])]

    async def get_service_operations(self, service_name: str) -> list[str]:
        """Get all operations linked to a specific service."""
        logger.debug(f"Getting operations for Dynatrace service: {service_name}")

        response = await self.client.get(f"/api/v2/traces/services/{service_name}/operations")
        response.raise_for_status()

        data = response.json()
        return [str(op) for op in data.get("operations", [])]

    async def health_check(self) -> HealthCheckResponse:
        """Verify Dynatrace connectivity status."""
        logger.debug("Checking Dynatrace backend health")
        try:
            # Quick request to verify API token authorization works
            await self.list_services()
            return HealthCheckResponse(
                status="healthy",
                backend="dynatrace",
                url=self.url,
            )
        except Exception as e:
            return HealthCheckResponse(
                status="unhealthy",
                backend="dynatrace",
                url=self.url,
                error=str(e),
            )

    def _parse_dynatrace_trace(self, trace_data: dict[str, Any]) -> TraceData | None:
        """Convert a raw Dynatrace trace JSON layout into a TraceData object model."""
        try:
            trace_id = trace_data.get("traceId")
            if not trace_id:
                return None

            spans_raw = trace_data.get("spans", [])
            spans: list[SpanData] = []

            for span_raw in spans_raw:
                # Map raw properties safely to model requirements
                start_time_ms = span_raw.get("startTime", 0)
                duration_ms = span_raw.get("durationMs", 0)
                
                attributes_dict = span_raw.get("attributes", {})
                span_attributes = SpanAttributes(**attributes_dict)

                # Determine the functional status code representation
                status = "OK"
                if span_raw.get("statusCode") == "ERROR" or attributes_dict.get("error"):
                    status = "ERROR"

                spans.append(
                    SpanData(
                        trace_id=trace_id,
                        span_id=str(span_raw.get("spanId")),
                        parent_span_id=span_raw.get("parentSpanId"),
                        operation_name=str(span_raw.get("name", "unknown")),
                        service_name=str(span_raw.get("serviceName", "unknown")),
                        start_time=datetime.fromtimestamp(start_time_ms / 1000),
                        duration_ms=duration_ms,
                        status=status,  # type: ignore
                        attributes=span_attributes,
                        events=[],
                    )
                )

            if not spans:
                return None

            # Calculate overall bounding metrics
            trace_start = min(s.start_time for s in spans)
            trace_duration = sum(s.duration_ms for s in spans)
            trace_status = "ERROR" if any(s.status == "ERROR" for s in spans) else "OK"

            return TraceData(
                trace_id=trace_id,
                spans=spans,
                start_time=trace_start,
                duration_ms=trace_duration,
                service_name=spans[0].service_name,
                root_operation=spans[0].operation_name,
                status=trace_status,  # type: ignore
            )
        except Exception as e:
            logger.error(f"Error parsing Dynatrace trace structural metrics: {e}")