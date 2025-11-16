"""Expensive traces tool implementation."""

import json

from opentelemetry_mcp.backends.base import BaseBackend
from opentelemetry_mcp.models import LLMSpanAttributes, TraceQuery
from opentelemetry_mcp.utils import parse_iso_timestamp


async def get_expensive_traces(
    backend: BaseBackend,
    limit: int = 10,
    start_time: str | None = None,
    end_time: str | None = None,
    min_tokens: int | None = None,
    service_name: str | None = None,
    gen_ai_request_model: str | None = None,
    gen_ai_response_model: str | None = None,
) -> str:
    """Find traces with highest token usage.

    Args:
        backend: Backend instance to query
        limit: Maximum number of traces to return (default: 10)
        start_time: Start time (ISO 8601 format)
        end_time: End time (ISO 8601 format)
        min_tokens: Minimum token count threshold
        service_name: Filter by service name
        gen_ai_request_model: Filter by requested model name
        gen_ai_response_model: Filter by actual model used

    Returns:
        JSON string with top N most expensive traces
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
            limit=min(limit * 10, 1000),  # Fetch more to ensure we get enough expensive ones
        )

        # Search traces
        trace_summaries = await backend.search_traces(query)

        # Collect trace data with token counts
        expensive_traces = []

        for summary in trace_summaries:
            # Get full trace to access LLM spans
            trace = await backend.get_trace(summary.trace_id)

            total_tokens = 0
            total_prompt_tokens = 0
            total_completion_tokens = 0
            models_used = set()

            for span in trace.llm_spans:
                llm_attrs = LLMSpanAttributes.from_span(span)
                if not llm_attrs:
                    continue

                # Calculate total tokens for this span
                if llm_attrs.total_tokens:
                    total_tokens += llm_attrs.total_tokens
                if llm_attrs.prompt_tokens:
                    total_prompt_tokens += llm_attrs.prompt_tokens
                if llm_attrs.completion_tokens:
                    total_completion_tokens += llm_attrs.completion_tokens

                # Track models
                model = llm_attrs.response_model or llm_attrs.request_model
                if model:
                    models_used.add(model)

            # Skip if below minimum threshold
            if min_tokens and total_tokens < min_tokens:
                continue

            # Skip traces with no LLM usage
            if total_tokens == 0:
                continue

            expensive_traces.append(
                {
                    "trace_id": trace.trace_id,
                    "service_name": trace.service_name,
                    "operation_name": trace.root_operation,
                    "start_time": trace.start_time.isoformat(),
                    "duration_ms": round(trace.duration_ms, 2),
                    "models": sorted(list(models_used)),
                    "tokens": {
                        "prompt": total_prompt_tokens,
                        "completion": total_completion_tokens,
                        "total": total_tokens,
                    },
                    "status": trace.status,
                    "has_errors": trace.has_errors,
                }
            )

        # Sort by total tokens descending and take top N
        expensive_traces.sort(key=lambda x: x["tokens"]["total"], reverse=True)  # type: ignore[index]
        top_traces = expensive_traces[:limit]

        result = {
            "count": len(top_traces),
            "traces": top_traces,
        }

        return json.dumps(result, indent=2)

    except Exception as e:
        return json.dumps({"error": f"Failed to get expensive traces: {str(e)}"})
