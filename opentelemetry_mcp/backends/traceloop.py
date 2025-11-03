"""Traceloop backend implementation for querying Opentelemetry traces."""

import logging
from datetime import datetime, timedelta
from typing import Any, Literal

import httpx

from opentelemetry_mcp.attributes import HealthCheckResponse, SpanAttributes, SpanEvent
from opentelemetry_mcp.backends.base import BaseBackend
from opentelemetry_mcp.models import SpanData, TraceData, TraceQuery

logger = logging.getLogger(__name__)


class TraceloopBackend(BaseBackend):
    """Traceloop API backend implementation.

    Implements the Traceloop API v2 for querying OpenTelemetry traces
    with Opentelemetry semantic conventions. Uses hardcoded project_id "default"
    as the Traceloop backend resolves the actual project from the API key.
    """

    def __init__(self, url: str, api_key: str | None = None, timeout: float = 30.0):
        """Initialize Traceloop backend.

        Args:
            url: Traceloop API base URL (e.g., https://api.traceloop.com)
            api_key: API key for authentication (required, contains project info)
            timeout: Request timeout in seconds
        """
        super().__init__(url, api_key, timeout)

        if not self.api_key:
            raise ValueError("Traceloop backend requires an API key")

        # Use "default" as project_id - Traceloop resolves actual project from API key
        self.project_id = "default"

    def _create_headers(self) -> dict[str, str]:
        """Create headers for Traceloop API requests.

        Returns:
            Dictionary with Bearer token and Content-Type headers
        """
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    async def search_traces(self, query: TraceQuery) -> list[TraceData]:
        """Search for traces using Traceloop API.

        Uses the root-spans endpoint to get trace-level data with aggregated metrics.

        Args:
            query: Trace query parameters

        Returns:
            List of matching traces

        Raises:
            httpx.HTTPError: If the API request fails
        """
        logger.debug(f"Searching traces with query: {query}")

        # Build filter array
        filters = []

        # Service filter
        if query.service_name:
            filters.append(
                {"field": "service.name", "operator": "equals", "value": query.service_name}
            )

        # Operation/span name filter
        if query.operation_name:
            filters.append(
                {"field": "span_name", "operator": "equals", "value": query.operation_name}
            )

        # LLM provider filter (gen_ai.system)
        if query.gen_ai_system:
            filters.append(
                {
                    "field": "span_attributes.gen_ai.system",
                    "operator": "equals",
                    "value": query.gen_ai_system,
                }
            )

        # Model filter (gen_ai.request.model)
        if query.gen_ai_model:
            filters.append(
                {
                    "field": "span_attributes.gen_ai.request.model",
                    "operator": "equals",
                    "value": query.gen_ai_model,
                }
            )

        # Duration filter (convert seconds to milliseconds)
        if query.min_duration_ms:
            filters.append(
                {
                    "field": "duration",
                    "operator": "greater_than",
                    "value": str(query.min_duration_ms),
                }
            )
        if query.max_duration_ms:
            filters.append(
                {
                    "field": "duration",
                    "operator": "less_than",
                    "value": str(query.max_duration_ms),
                }
            )

        # Error filter
        if query.has_error:
            filters.append({"field": "status_code", "operator": "equals", "value": "ERROR"})

        # Additional tag filters
        for key, value in query.tags.items():
            filters.append(
                {
                    "field": f"{key}",
                    "operator": "equals",
                    "value": value,
                }
            )

        # Build request body
        body = {
            "filters": filters,
            "logical_operator": "and",
            "sort_by": "timestamp",
            "sort_order": "DESC",
            "limit": query.limit,
        }

        # Add time range (convert to seconds for Traceloop API)
        if query.start_time:
            body["from_timestamp_sec"] = int(query.start_time.timestamp())
        if query.end_time:
            body["to_timestamp_sec"] = int(query.end_time.timestamp())

        # Make request
        endpoint = f"/v2/projects/{self.project_id}/traces/root-spans"
        logger.debug(f"POST {endpoint} with body: {body}")

        response = await self.client.post(endpoint, json=body)
        response.raise_for_status()

        data = response.json()
        root_spans_data = data.get("root_spans", {})
        root_spans = root_spans_data.get("data", [])

        logger.debug(f"Found {len(root_spans)} traces")

        # Convert to TraceData
        traces = []
        for root_span in root_spans:
            trace = self._convert_root_span_to_trace(root_span)
            if trace:
                traces.append(trace)

        return traces

    async def get_trace(self, trace_id: str) -> TraceData:
        """Get a specific trace by ID from Traceloop.

        Fetches all spans for the trace with full details.

        Args:
            trace_id: Trace identifier

        Returns:
            Complete trace data with all spans

        Raises:
            ValueError: If trace not found
            httpx.HTTPError: If the API request fails
        """
        logger.debug(f"Getting trace: {trace_id}")

        endpoint = f"/v2/projects/{self.project_id}/traces/{trace_id}/spans"
        response = await self.client.get(endpoint)
        response.raise_for_status()

        data = response.json()
        spans_data = data.get("spans", [])

        if not spans_data:
            raise ValueError(f"Trace {trace_id} not found")

        logger.debug(f"Found {len(spans_data)} spans for trace {trace_id}")

        # Convert spans to TraceData
        trace = self._convert_spans_to_trace(trace_id, spans_data)
        if trace is None:
            raise ValueError(f"Failed to parse trace {trace_id}")
        return trace

    async def list_services(self) -> list[str]:
        """List all services from Traceloop.

        Queries for unique service names from recent data (last 7 days).

        Returns:
            List of service names

        Raises:
            httpx.HTTPError: If the API request fails
        """
        logger.debug("Listing services")

        # Query recent data (last 7 days)
        body = {
            "attribute_name": "service_name",
            "from_timestamp_sec": int((datetime.now() - timedelta(days=7)).timestamp()),
            "to_timestamp_sec": int(datetime.now().timestamp()),
        }

        endpoint = f"/v2/projects/{self.project_id}/spans/attributes/values"
        response = await self.client.post(endpoint, json=body)
        response.raise_for_status()

        data = response.json()
        services_raw = data.get("values", [])
        services: list[str] = [str(s) for s in services_raw]

        logger.debug(f"Found {len(services)} services")
        return services

    async def get_service_operations(self, service_name: str) -> list[str]:
        """Get operations for a service from Traceloop.

        Returns workflow names which represent high-level operations.

        Args:
            service_name: Service name (currently not used for filtering)

        Returns:
            List of operation/workflow names

        Raises:
            httpx.HTTPError: If the API request fails
        """
        logger.debug(f"Getting operations for service: {service_name}")

        endpoint = f"/v2/projects/{self.project_id}/spans/workflow-names"

        # Get recent data (last 7 days)
        params = {
            "start_time": int((datetime.now() - timedelta(days=7)).timestamp() * 1000),
            "end_time": int(datetime.now().timestamp() * 1000),
        }

        response = await self.client.get(endpoint, params=params)
        response.raise_for_status()

        workflows_raw = response.json()
        workflows: list[str] = [str(w) for w in workflows_raw]

        logger.debug(f"Found {len(workflows)} workflows")
        return workflows

    async def health_check(self) -> HealthCheckResponse:
        """Check Traceloop backend health.

        Returns:
            Health status information
        """
        logger.debug("Checking Traceloop backend health")

        try:
            # Health endpoint is at root, not /v2
            health_url = self.url + "health"
            # Make request without base_url override
            async with httpx.AsyncClient(timeout=self.timeout) as temp_client:
                response = await temp_client.get(health_url)
                response.raise_for_status()

            return HealthCheckResponse(
                status="healthy",
                backend="traceloop",
                url=self.url,
                project_id=self.project_id,
            )
        except Exception as e:
            logger.warning(f"Health check failed: {e}")
            return HealthCheckResponse(
                status="unhealthy",
                backend="traceloop",
                url=self.url,
                project_id=self.project_id,
                error=str(e),
            )

    @staticmethod
    def _transform_llm_attributes_to_gen_ai(attrs: dict[str, Any]) -> dict[str, Any]:
        """
        Transform Traceloop's llm.* attributes to gen_ai.* format.

        This adapter method handles the backend-specific attribute naming convention
        by mapping llm.* attributes to the canonical gen_ai.* format used throughout
        the codebase.

        Args:
            attrs: Raw attribute dictionary from Traceloop API

        Returns:
            Transformed attribute dictionary with gen_ai.* keys
        """
        transformed = dict(attrs)

        # Mapping from llm.* to gen_ai.* format
        attribute_mappings = {
            "llm.vendor": "gen_ai.system",
            "llm.request.model": "gen_ai.request.model",
            "llm.response.model": "gen_ai.response.model",
            "llm.operation.name": "gen_ai.operation.name",
            "llm.request.temperature": "gen_ai.request.temperature",
            "llm.request.top_p": "gen_ai.request.top_p",
            "llm.request.max_tokens": "gen_ai.request.max_tokens",
            "llm.request.is_streaming": "gen_ai.request.is_streaming",
            "llm.usage.prompt_tokens": "gen_ai.usage.prompt_tokens",
            "llm.usage.input_tokens": "gen_ai.usage.input_tokens",
            "llm.usage.completion_tokens": "gen_ai.usage.completion_tokens",
            "llm.usage.output_tokens": "gen_ai.usage.output_tokens",
            "llm.usage.total_tokens": "gen_ai.usage.total_tokens",
        }

        # Transform llm.* keys to gen_ai.* keys if they exist
        for llm_key, gen_ai_key in attribute_mappings.items():
            if llm_key in transformed:
                # Only transform if gen_ai.* key doesn't already exist (prefer gen_ai.*)
                if gen_ai_key not in transformed:
                    transformed[gen_ai_key] = transformed[llm_key]
                # Keep the original llm.* key for backward compatibility
                # (it will be stored as a field alias in SpanAttributes)

        return transformed

    def _convert_root_span_to_trace(self, root_span: dict[str, Any]) -> TraceData | None:
        """Convert Traceloop root span to TraceData.

        Args:
            root_span: Root span data from API

        Returns:
            TraceData with aggregated metrics or None if parsing fails
        """
        try:
            # Extract and transform span attributes from llm.* to gen_ai.* format
            raw_attrs = root_span.get("span_attributes", {})
            transformed_attrs = self._transform_llm_attributes_to_gen_ai(raw_attrs)

            # Create strongly-typed SpanAttributes
            span_attributes = SpanAttributes(**transformed_attrs)

            # Create span
            span = SpanData(
                trace_id=root_span["trace_id"],
                span_id=root_span["span_id"],
                parent_span_id=root_span.get("parent_span_id"),
                operation_name=root_span["span_name"],
                service_name=root_span.get("service_name", ""),
                start_time=datetime.fromtimestamp(
                    root_span["timestamp"] / 1000
                ),  # Convert ms to seconds
                duration_ms=float(root_span["duration"]),
                status=self._status_code_to_status(root_span.get("status_code", "UNSET")),
                attributes=span_attributes,
            )

            # Determine overall status
            trace_status = self._status_code_to_status(root_span.get("status_code", "UNSET"))

            # Create trace with aggregated data
            return TraceData(
                trace_id=root_span["trace_id"],
                spans=[span],
                start_time=span.start_time,
                duration_ms=float(root_span["duration"]),
                service_name=span.service_name,
                root_operation=span.operation_name,
                status=trace_status,
            )

        except Exception as e:
            logger.error(f"Error converting root span to trace: {e}")
            return None

    def _convert_spans_to_trace(
        self, trace_id: str, spans_data: list[dict[str, Any]]
    ) -> TraceData | None:
        """Convert Traceloop spans array to TraceData.

        Args:
            trace_id: Trace identifier
            spans_data: List of span data from API

        Returns:
            Complete TraceData with all spans
        """
        spans = []

        for span_data in spans_data:
            # Extract and transform span attributes from llm.* to gen_ai.* format
            raw_attrs = span_data.get("span_attributes", {})
            transformed_attrs = self._transform_llm_attributes_to_gen_ai(raw_attrs)

            # Create strongly-typed SpanAttributes
            span_attributes = SpanAttributes(**transformed_attrs)

            # Transform events if present
            events_data = span_data.get("events", [])
            events = [
                SpanEvent(
                    name=event.get("name", ""),
                    timestamp=event.get("timestamp", 0),
                    attributes=event.get("attributes", {}),
                )
                for event in events_data
            ]

            span = SpanData(
                trace_id=span_data["trace_id"],
                span_id=span_data["span_id"],
                parent_span_id=span_data.get("parent_span_id"),
                operation_name=span_data["span_name"],
                service_name="",  # Not in detailed span response
                start_time=datetime.fromtimestamp(
                    span_data["timestamp"] / 1000
                ),  # Convert ms to seconds
                duration_ms=float(span_data["duration"]),
                status=self._status_code_to_status(span_data.get("status_code", "UNSET")),
                attributes=span_attributes,
                events=events,
            )

            spans.append(span)

        # Find root span
        root_spans = [s for s in spans if not s.parent_span_id]
        root_span = root_spans[0] if root_spans else spans[0]

        # Calculate trace duration
        if spans:
            start_times = [s.start_time for s in spans]
            trace_start = min(start_times)
            # Find the maximum end time
            end_times = [
                datetime.fromtimestamp(s.start_time.timestamp() + (s.duration_ms / 1000))
                for s in spans
            ]
            trace_end = max(end_times)
            trace_duration_ms = (trace_end - trace_start).total_seconds() * 1000
        else:
            trace_start = root_span.start_time
            trace_duration_ms = root_span.duration_ms

        # Determine status
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
            status=self._status_code_to_status(trace_status),
        )

    # Trims the prefix STATUS_CODE_ from the status code
    def _status_code_to_status(self, status_code: str) -> Literal["OK", "ERROR", "UNSET"]:
        """Convert Traceloop status code to standardized status."""
        normalized = status_code.replace("STATUS_CODE_", "").upper()
        if normalized in ("OK", "ERROR", "UNSET"):
            return normalized  # type: ignore[return-value]
        return "UNSET"
