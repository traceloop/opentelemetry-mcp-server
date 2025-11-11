"""Model statistics tool implementation."""

import json
from collections.abc import Sequence

from opentelemetry_mcp.backends.base import BaseBackend
from opentelemetry_mcp.models import LLMSpanAttributes, TraceQuery
from opentelemetry_mcp.utils import parse_iso_timestamp


def calculate_percentiles(values: Sequence[float | int]) -> dict[str, float]:
    """Calculate percentile statistics for a list of values.

    Args:
        values: List of numeric values

    Returns:
        Dictionary with mean, median, p50, p95, p99
    """
    if not values:
        return {"mean": 0.0, "median": 0.0, "p50": 0.0, "p95": 0.0, "p99": 0.0}

    sorted_values = sorted(values)
    length = len(sorted_values)

    def percentile(p: float) -> float:
        """Calculate percentile value."""
        index = (length - 1) * p
        lower = int(index)
        upper = min(lower + 1, length - 1)
        weight = index - lower
        return sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight

    return {
        "mean": sum(values) / length,
        "median": percentile(0.5),
        "p50": percentile(0.5),
        "p95": percentile(0.95),
        "p99": percentile(0.99),
    }


async def get_model_stats(
    backend: BaseBackend,
    model_name: str,
    start_time: str | None = None,
    end_time: str | None = None,
    service_name: str | None = None,
    limit: int = 1000,
) -> str:
    """Get detailed performance statistics for a specific model.

    Note: This function uses an N+1 query pattern where it first searches for traces,
    then fetches each trace individually to access LLM span details. This can cause
    performance issues with large result sets. Consider using backend-side filtering
    for model names when available to reduce the number of traces fetched.

    Args:
        backend: Backend instance to query
        model_name: Model name to analyze (e.g., "gpt-4", "claude-3-opus")
        start_time: Start time (ISO 8601 format)
        end_time: End time (ISO 8601 format)
        service_name: Filter by service name
        limit: Maximum number of traces to analyze (default: 1000)

    Returns:
        JSON string with comprehensive model statistics
    """
    # Parse timestamps
    start_dt, error = parse_iso_timestamp(start_time, "start_time")
    if error:
        return json.dumps({"error": error})

    end_dt, error = parse_iso_timestamp(end_time, "end_time")
    if error:
        return json.dumps({"error": error})

    try:
        # Build query to fetch traces - search for model in both request and response
        # We need to fetch traces where the model appears in either field
        # Since we can only use AND logic for multiple filters, we'll fetch without model filter
        # and filter in-memory to support OR logic (request_model OR response_model)
        query = TraceQuery(
            start_time=start_dt,
            end_time=end_dt,
            service_name=service_name,
            limit=limit,
        )

        # Search traces
        trace_summaries = await backend.search_traces(query)

        # Collect metrics for analysis
        durations: list[float] = []
        prompt_tokens_list: list[int] = []
        completion_tokens_list: list[int] = []
        total_tokens_list: list[int] = []
        finish_reasons_count: dict[str, int] = {}
        error_count = 0
        success_count = 0
        request_count = 0

        for summary in trace_summaries:
            # Get full trace to access LLM spans
            trace = await backend.get_trace(summary.trace_id)

            for span in trace.llm_spans:
                llm_attrs = LLMSpanAttributes.from_span(span)
                if not llm_attrs:
                    continue

                # Check if this span is for the requested model
                span_model = llm_attrs.response_model or llm_attrs.request_model
                if span_model != model_name:
                    continue

                request_count += 1

                # Collect duration
                durations.append(span.duration_ms)

                # Collect token metrics
                if llm_attrs.prompt_tokens:
                    prompt_tokens_list.append(llm_attrs.prompt_tokens)
                if llm_attrs.completion_tokens:
                    completion_tokens_list.append(llm_attrs.completion_tokens)
                if llm_attrs.total_tokens:
                    total_tokens_list.append(llm_attrs.total_tokens)

                # Collect finish reasons
                if llm_attrs.finish_reasons:
                    for reason in llm_attrs.finish_reasons:
                        finish_reasons_count[reason] = finish_reasons_count.get(reason, 0) + 1

                # Count errors
                if span.has_error:
                    error_count += 1
                else:
                    success_count += 1

        # Calculate statistics
        if request_count == 0:
            return json.dumps(
                {"error": f"No traces found for model '{model_name}' in the specified time range"}
            )

        result = {
            "model": model_name,
            "request_count": request_count,
            "success_count": success_count,
            "error_count": error_count,
            "success_rate": round(success_count / request_count * 100, 2)
            if request_count > 0
            else 0,
            "error_rate": round(error_count / request_count * 100, 2) if request_count > 0 else 0,
            "duration_ms": calculate_percentiles(durations),
            "tokens": {
                "prompt": calculate_percentiles(prompt_tokens_list),
                "completion": calculate_percentiles(completion_tokens_list),
                "total": calculate_percentiles(total_tokens_list),
            },
            "finish_reasons": finish_reasons_count if finish_reasons_count else None,
        }

        return json.dumps(result, indent=2)

    except Exception as e:
        return json.dumps({"error": f"Failed to get model stats: {str(e)}"})
