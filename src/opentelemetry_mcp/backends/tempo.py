"""Grafana Tempo backend implementation with TraceQL support."""

import logging
from datetime import datetime
from typing import Any, Literal

from opentelemetry_mcp.attributes import HealthCheckResponse, SpanAttributes, SpanEvent
from opentelemetry_mcp.backends.base import BaseBackend
from opentelemetry_mcp.models import SpanData, TraceData, TraceQuery

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

    async def search_traces(self, query: TraceQuery) -> list[TraceData]:
        """Search traces using TraceQL.

        Args:
            query: Trace query parameters

        Returns:
            List of matching traces

        Raises:
            httpx.HTTPError: If API request fails
        """
        # Build TraceQL query
        traceql = self._build_traceql_query(query)
        logger.debug(f"Executing TraceQL: {traceql}")

        params: dict[str, str | int] = {"q": traceql, "limit": query.limit}

        if query.start_time:
            params["start"] = int(query.start_time.timestamp())
        if query.end_time:
            params["end"] = int(query.end_time.timestamp())

        response = await self.client.get("/api/search", params=params)
        response.raise_for_status()

        data = response.json()
        traces = []

        # Tempo search returns trace IDs, we need to fetch full traces
        # WARNING: Each trace requires a separate HTTP request, so limit to avoid performance issues
        trace_results = data.get("traces", [])
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
                    trace = self._parse_tempo_trace(trace_data)
                    if trace:
                        traces.append(trace)
                except Exception as e:
                    logger.warning(f"Failed to fetch trace {trace_id}: {e}")

        return traces

    async def get_trace(self, trace_id: str) -> TraceData:
        """Get a specific trace by ID from Tempo."""
        response = await self.client.get(f"/api/traces/{trace_id}")
        response.raise_for_status()
        data = response.json()
        trace = self._parse_tempo_trace(data)
        if not trace:
            raise ValueError(f"Failed to parse trace {trace_id}")
        return trace

    async def list_services(self) -> list[str]:
        """List all services from Tempo.

        Returns:
            List of service names

        Raises:
            httpx.HTTPError: If API request fails
        """
        logger.debug("Listing services")

        # Tempo uses tag values endpoint
        response = await self.client.get("/api/search/tag/service.name/values")
        response.raise_for_status()

        data = response.json()
        tag_values_raw = data.get("tagValues", [])
        return [str(v) for v in tag_values_raw]

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
        for trace_result in data.get("traces", []):
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
            # Try to get tag values as a health check
            response = await self.client.get("/api/search/tags")
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

    def _build_traceql_query(self, query: TraceQuery) -> str:
        """Build TraceQL query from query parameters.

        Args:
            query: Trace query parameters

        Returns:
            TraceQL query string
        """
        conditions = []

        if query.service_name:
            conditions.append(f'resource.service.name = "{query.service_name}"')

        if query.operation_name:
            conditions.append(f'name = "{query.operation_name}"')

        if query.min_duration_ms:
            conditions.append(f"duration > {query.min_duration_ms}ms")

        if query.max_duration_ms:
            conditions.append(f"duration < {query.max_duration_ms}ms")

        # Add tag filters
        for key, value in query.tags.items():
            conditions.append(f'span.{key} = "{value}"')

        # Add Opentelemetry filters
        if query.gen_ai_system:
            conditions.append(f'span.gen_ai.system = "{query.gen_ai_system}"')

        if query.gen_ai_model:
            conditions.append(f'span.gen_ai.request.model = "{query.gen_ai_model}"')

        if query.has_error:
            conditions.append("status = error")

        # If we have gen_ai filters but no explicit system, match any LLM trace
        # This is important for get_llm_usage to only return LLM traces
        if not query.gen_ai_system and not query.gen_ai_model and not conditions:
            # Empty query - match all LLM traces by default
            return '{span.gen_ai.system=~".+"}'

        # Combine conditions
        if conditions:
            return "{ " + " && ".join(conditions) + " }"
        else:
            return "{}"  # Match all traces

    def _parse_tempo_trace(self, trace_data: dict[str, Any]) -> TraceData | None:
        """Parse Tempo trace format to TraceData.

        Tempo returns OTLP JSON format, which is different from Jaeger.

        Args:
            trace_data: Raw Tempo trace data

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
            trace_id = None

            for batch in batches:
                resource = batch.get("resource", {})
                resource_attrs = self._parse_otlp_attributes(resource.get("attributes", []))
                service_name = resource_attrs.get("service.name", "unknown")

                for scope_span in batch.get("scopeSpans", []):
                    for span_data in scope_span.get("spans", []):
                        span = self._parse_otlp_span(span_data, str(service_name))
                        if span:
                            all_spans.append(span)
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
            status_code = status_data.get("code", 0)
            status: Literal["OK", "ERROR", "UNSET"] = "UNSET"
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
