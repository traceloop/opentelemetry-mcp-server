"""Search spans tool implementation."""

import json
from typing import Any

from pydantic import ValidationError

from opentelemetry_mcp.backends.base import BaseBackend
from opentelemetry_mcp.models import Filter, SpanQuery, SpanSummary
from opentelemetry_mcp.utils import parse_iso_timestamp


async def search_spans(
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
    """Search for individual OpenTelemetry spans with optional filters.

    Unlike search_traces, this returns individual spans rather than grouped traces,
    which is useful for analyzing specific operations or finding spans with certain
    characteristics (e.g., LLM tool calls with traceloop.span.kind == tool).

    Args:
        backend: Backend instance to query
        service_name: Filter by service name
        operation_name: Filter by operation/span name
        start_time: Start time (ISO 8601 format)
        end_time: End time (ISO 8601 format)
        min_duration_ms: Minimum span duration in milliseconds
        max_duration_ms: Maximum span duration in milliseconds
        gen_ai_system: Filter by LLM provider
        gen_ai_request_model: Filter by requested model name
        gen_ai_response_model: Filter by actual model used
        has_error: Filter spans with errors
        tags: Additional tag filters as key-value pairs
        filters: Generic filter conditions (list of filter objects)
        limit: Maximum number of spans to return (1-1000)

    Returns:
        JSON string with span summaries

    Example filter to find LLM tool calls:
        {
            "field": "traceloop.span.kind",
            "operator": "equals",
            "value": "tool",
            "value_type": "string"
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

    # Build query
    try:
        query = SpanQuery(
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
        spans = await backend.search_spans(query)

        # Convert to summaries
        summaries = [SpanSummary.from_span(span) for span in spans]

        # Return as JSON
        result = {
            "count": len(summaries),
            "spans": [s.model_dump(mode="json") for s in summaries],
        }

        return json.dumps(result, indent=2, default=str)

    except Exception as e:
        return json.dumps({"error": f"Failed to search spans: {str(e)}"})
