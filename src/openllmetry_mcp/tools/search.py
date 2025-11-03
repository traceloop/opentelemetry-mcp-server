"""Search traces tool implementation."""

import json
from datetime import datetime

from openllmetry_mcp.backends.base import BaseBackend
from openllmetry_mcp.models import TraceQuery, TraceSummary


async def search_traces(
    backend: BaseBackend,
    service_name: str | None = None,
    operation_name: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    min_duration_ms: int | None = None,
    max_duration_ms: int | None = None,
    gen_ai_system: str | None = None,
    gen_ai_model: str | None = None,
    has_error: bool | None = None,
    tags: dict[str, str] | None = None,
    limit: int = 100,
) -> str:
    """Search for OpenTelemetry traces with optional filters.

    Args:
        backend: Backend instance to query
        service_name: Filter by service name
        operation_name: Filter by operation/span name
        start_time: Start time (ISO 8601 format)
        end_time: End time (ISO 8601 format)
        min_duration_ms: Minimum trace duration in milliseconds
        max_duration_ms: Maximum trace duration in milliseconds
        gen_ai_system: Filter by LLM provider (openai, anthropic, etc.)
        gen_ai_model: Filter by LLM model name
        has_error: Filter traces with errors (true/false)
        tags: Additional tag filters as key-value pairs
        limit: Maximum number of traces to return (1-1000)

    Returns:
        JSON string with trace summaries
    """
    # Parse timestamps
    start_dt = None
    end_dt = None

    if start_time:
        try:
            start_dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
        except ValueError as e:
            return json.dumps({"error": f"Invalid start_time format: {e}"})

    if end_time:
        try:
            end_dt = datetime.fromisoformat(end_time.replace("Z", "+00:00"))
        except ValueError as e:
            return json.dumps({"error": f"Invalid end_time format: {e}"})

    # Build query
    query = TraceQuery(
        service_name=service_name,
        operation_name=operation_name,
        start_time=start_dt,
        end_time=end_dt,
        min_duration_ms=min_duration_ms,
        max_duration_ms=max_duration_ms,
        gen_ai_system=gen_ai_system,
        gen_ai_model=gen_ai_model,
        has_error=has_error,
        tags=tags or {},
        limit=limit,
    )

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
