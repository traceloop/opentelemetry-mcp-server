"""LLM usage metrics tool implementation."""

import json
from typing import Any

from opentelemetry_mcp.backends.base import BaseBackend
from opentelemetry_mcp.models import LLMSpanAttributes, TraceQuery, UsageMetrics
from opentelemetry_mcp.utils import parse_iso_timestamp


async def get_llm_usage(
    backend: BaseBackend,
    start_time: str | None = None,
    end_time: str | None = None,
    service_name: str | None = None,
    gen_ai_system: str | None = None,
    gen_ai_request_model: str | None = None,
    gen_ai_response_model: str | None = None,
    limit: int = 1000,
) -> str:
    """Get aggregated LLM usage metrics for a time period.

    Args:
        backend: Backend instance to query
        start_time: Start time (ISO 8601 format)
        end_time: End time (ISO 8601 format)
        service_name: Filter by service name
        gen_ai_system: Filter by LLM provider (openai, anthropic, etc.)
        gen_ai_request_model: Filter by requested model name
        gen_ai_response_model: Filter by actual model used
        limit: Maximum number of traces to analyze (default: 1000)

    Returns:
        JSON string with aggregated usage metrics
    """
    # Parse timestamps
    start_dt, error = parse_iso_timestamp(start_time, "start_time")
    if error:
        return json.dumps({"error": error})

    end_dt, error = parse_iso_timestamp(end_time, "end_time")
    if error:
        return json.dumps({"error": error})

    # Build query to find LLM traces
    query = TraceQuery(
        service_name=service_name,
        start_time=start_dt,
        end_time=end_dt,
        gen_ai_system=gen_ai_system,
        gen_ai_request_model=gen_ai_request_model,
        gen_ai_response_model=gen_ai_response_model,
        limit=limit,
    )

    try:
        # Search for traces
        traces = await backend.search_traces(query)

        # Aggregate usage metrics
        metrics = UsageMetrics()

        for trace in traces:
            for span in trace.llm_spans:
                llm_attrs = LLMSpanAttributes.from_span(span)
                if llm_attrs:
                    metrics.add_span(span, llm_attrs)

        # Build result
        result: dict[str, Any] = {
            "period": {
                "start_time": start_dt.isoformat() if start_dt else None,
                "end_time": end_dt.isoformat() if end_dt else None,
            },
            "filters": {
                "service_name": service_name,
                "gen_ai_system": gen_ai_system,
                "gen_ai_request_model": gen_ai_request_model,
                "gen_ai_response_model": gen_ai_response_model,
            },
            "summary": {
                "total_requests": metrics.request_count,
                "total_prompt_tokens": metrics.prompt_tokens,
                "total_completion_tokens": metrics.completion_tokens,
                "total_tokens": metrics.total_tokens,
            },
            "by_model": {},
            "by_service": {},
        }

        # Add model breakdown
        by_model: dict[str, Any] = result["by_model"]
        for model, model_metrics in metrics.by_model.items():
            by_model[model] = {
                "requests": model_metrics.request_count,
                "prompt_tokens": model_metrics.prompt_tokens,
                "completion_tokens": model_metrics.completion_tokens,
                "total_tokens": model_metrics.total_tokens,
            }

        # Add service breakdown
        by_service: dict[str, Any] = result["by_service"]
        for service, service_metrics in metrics.by_service.items():
            by_service[service] = {
                "requests": service_metrics.request_count,
                "prompt_tokens": service_metrics.prompt_tokens,
                "completion_tokens": service_metrics.completion_tokens,
                "total_tokens": service_metrics.total_tokens,
            }

        return json.dumps(result, indent=2, default=str)

    except Exception as e:
        return json.dumps({"error": f"Failed to get usage metrics: {str(e)}"})
