"""Search traces tool implementation."""

import json
from typing import Any

from pydantic import ValidationError

from opentelemetry_mcp.backends.base import BaseBackend
from opentelemetry_mcp.models import Filter, TraceQuery, TraceSummary
from opentelemetry_mcp.utils import parse_iso_timestamp


async def search_traces(
    backend: BaseBackend,
    service_name: str | None = None,
    operation_name: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    min_duration_ms: int | None = None,
    max_duration_ms: int | None = None,
    gen_ai_system: str | None = None,
    gen_ai_request_model: str | None = None,
    gen_ai_response_model: str | None = None,
    has_error: bool | None = None,
    tags: dict[str, str] | None = None,
    filters: list[dict[str, Any]] | None = None,
    limit: int = 100,
) -> str:
    """Search for OpenTelemetry traces with optional filters.

    Supports both simple parameters and the new generic filter system.

    Args:
        backend: Backend instance to query
        service_name: Filter by service name
        operation_name: Filter by operation/span name
        start_time: Start time (ISO 8601 format)
        end_time: End time (ISO 8601 format)
        min_duration_ms: Minimum trace duration in milliseconds
        max_duration_ms: Maximum trace duration in milliseconds
        gen_ai_system: Filter by LLM provider
        gen_ai_request_model: Filter by requested model name
        gen_ai_response_model: Filter by actual model used
        has_error: Filter traces with errors
        tags: Additional tag filters as key-value pairs
        filters: Generic filter conditions (list of filter objects)
        limit: Maximum number of traces to return (1-1000)

    Returns:
        JSON string with trace summaries

    Example filter:
        {
            "field": "gen_ai.usage.prompt_tokens",
            "operator": "gt",
            "value": 1000,
            "value_type": "number"
        }
    """
    # Parse timestamps
    start_dt, error = parse_iso_timestamp(start_time, "start_time")
    if error:
        return json.dumps({"error": error})

    end_dt, error = parse_iso_timestamp(end_time, "end_time")
    if error:
        return json.dumps({"error": error})

    # Parse filters from dicts to Filter models
    filter_objects = []
    if filters:
        try:
            for filter_dict in filters:
                filter_obj = Filter(**filter_dict)
                filter_objects.append(filter_obj)
        except ValidationError as e:
            return json.dumps({"error": f"Invalid filter format: {e}"})
        except Exception as e:
            return json.dumps({"error": f"Failed to parse filters: {e}"})

    try:
        # Build query
        query = TraceQuery(
            service_name=service_name,
            operation_name=operation_name,
            start_time=start_dt,
            end_time=end_dt,
            min_duration_ms=min_duration_ms,
            max_duration_ms=max_duration_ms,
            gen_ai_system=gen_ai_system,
            gen_ai_request_model=gen_ai_request_model,
            gen_ai_response_model=gen_ai_response_model,
            has_error=has_error,
            tags=tags or {},
            filters=filter_objects,
            limit=limit,
        )
    except ValidationError as e:
        return json.dumps({"error": f"Invalid query parameters: {e}"})

    try:
        # Execute search
        traces = await backend.search_traces(query)

        # Convert to summaries
        summaries = [TraceSummary.from_trace(trace) for trace in traces]

        # Return as JSON
        result = {
            "count": len(summaries),
            "traces": [s.model_dump(mode="json") for s in summaries],
        }

        return json.dumps(result, indent=2, default=str)

    except Exception as e:
        return json.dumps({"error": f"Failed to search traces: {str(e)}"})
