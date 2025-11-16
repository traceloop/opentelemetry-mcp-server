"""Slow traces tool implementation."""

import json

from opentelemetry_mcp.backends.base import BaseBackend
from opentelemetry_mcp.models import LLMSpanAttributes, TraceQuery
from opentelemetry_mcp.utils import parse_iso_timestamp


async def get_slow_traces(
    backend: BaseBackend,
    limit: int = 10,
    start_time: str | None = None,
    end_time: str | None = None,
    min_duration_ms: int | None = None,
    service_name: str | None = None,
    gen_ai_request_model: str | None = None,
    gen_ai_response_model: str | None = None,
) -> str:
    """Find slowest LLM traces by duration.

    Args:
        backend: Backend instance to query
        limit: Maximum number of traces to return (default: 10)
        start_time: Start time (ISO 8601 format)
        end_time: End time (ISO 8601 format)
        min_duration_ms: Minimum duration threshold in milliseconds
        service_name: Filter by service name
        gen_ai_request_model: Filter by requested model name
        gen_ai_response_model: Filter by actual model used

    Returns:
        JSON string with top N slowest traces
    """
    # Parse timestamps
    start_dt, error = parse_iso_timestamp(start_time, "start_time")
    if error:
        return json.dumps({"error": error})

    end_dt, error = parse_iso_timestamp(end_time, "end_time")
    if error:
        return json.dumps({"error": error})

    try:
        # Build query to fetch traces (use larger limit to find top N)
        query = TraceQuery(
            start_time=start_dt,
            end_time=end_dt,
            service_name=service_name,
            gen_ai_request_model=gen_ai_request_model,
            gen_ai_response_model=gen_ai_response_model,
            min_duration_ms=min_duration_ms,
            limit=min(limit * 10, 1000),  # Fetch more to ensure we get enough slow ones
        )

        # Search traces
        trace_summaries = await backend.search_traces(query)

        # Collect trace data with durations
        slow_traces = []

        for summary in trace_summaries:
            # Get full trace to access LLM spans
            trace = await backend.get_trace(summary.trace_id)

            # Only include traces that have LLM spans
            if not trace.llm_spans:
                continue

            total_tokens = 0
            models_used = set()

            for span in trace.llm_spans:
                llm_attrs = LLMSpanAttributes.from_span(span)
                if not llm_attrs:
                    continue

                # Calculate total tokens
                if llm_attrs.total_tokens:
                    total_tokens += llm_attrs.total_tokens

                # Track models
                model = llm_attrs.response_model or llm_attrs.request_model
                if model:
                    models_used.add(model)

            slow_traces.append(
                {
                    "trace_id": trace.trace_id,
                    "service_name": trace.service_name,
                    "operation_name": trace.root_operation,
                    "start_time": trace.start_time.isoformat(),
                    "duration_ms": round(trace.duration_ms, 2),
                    "models": sorted(list(models_used)),
                    "total_tokens": total_tokens,
                    "llm_span_count": len(trace.llm_spans),
                    "status": trace.status,
                    "has_errors": trace.has_errors,
                }
            )

        # Sort by duration descending and take top N
        slow_traces.sort(key=lambda x: x["duration_ms"], reverse=True)  # type: ignore[arg-type, return-value]
        top_traces = slow_traces[:limit]

        result = {
            "count": len(top_traces),
            "traces": top_traces,
        }

        return json.dumps(result, indent=2)

    except Exception as e:
        return json.dumps({"error": f"Failed to get slow traces: {str(e)}"})
