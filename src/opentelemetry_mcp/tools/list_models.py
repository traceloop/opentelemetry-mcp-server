"""List LLM models tool implementation."""

import json
from typing import Any

from opentelemetry_mcp.backends.base import BaseBackend
from opentelemetry_mcp.models import LLMSpanAttributes, TraceQuery
from opentelemetry_mcp.utils import parse_iso_timestamp


async def list_models(
    backend: BaseBackend,
    start_time: str | None = None,
    end_time: str | None = None,
    service_name: str | None = None,
    gen_ai_system: str | None = None,
    limit: int = 1000,
) -> str:
    """List all LLM models being used with usage statistics.

    Args:
        backend: Backend instance to query
        start_time: Start time (ISO 8601 format)
        end_time: End time (ISO 8601 format)
        service_name: Filter by service name
        gen_ai_system: Filter by LLM provider (e.g., "openai", "anthropic")
        limit: Maximum number of traces to analyze (default: 1000)

    Returns:
        JSON string with list of models and their usage statistics
    """
    # Parse timestamps
    start_dt, error = parse_iso_timestamp(start_time, "start_time")
    if error:
        return json.dumps({"error": error})

    end_dt, error = parse_iso_timestamp(end_time, "end_time")
    if error:
        return json.dumps({"error": error})

    try:
        # Build query to fetch traces
        query = TraceQuery(
            start_time=start_dt,
            end_time=end_dt,
            service_name=service_name,
            gen_ai_system=gen_ai_system,
            limit=limit,
        )

        # Search traces
        trace_summaries = await backend.search_traces(query)

        # Track models with their statistics
        models_data: dict[str, dict[str, Any]] = {}

        for summary in trace_summaries:
            # Get full trace to access LLM spans
            trace = await backend.get_trace(summary.trace_id)

            for span in trace.llm_spans:
                llm_attrs = LLMSpanAttributes.from_span(span)
                if not llm_attrs:
                    continue

                # Get model name (prefer response_model, fallback to request_model)
                model = llm_attrs.response_model or llm_attrs.request_model
                if not model:
                    model = "unknown"

                # Initialize model entry if not exists
                if model not in models_data:
                    models_data[model] = {
                        "model": model,
                        "provider": llm_attrs.system,
                        "request_count": 0,
                        "first_seen": span.start_time.isoformat(),
                        "last_seen": span.start_time.isoformat(),
                    }

                # Update statistics
                models_data[model]["request_count"] += 1

                # Update timestamps
                span_time = span.start_time.isoformat()
                if span_time < models_data[model]["first_seen"]:
                    models_data[model]["first_seen"] = span_time
                if span_time > models_data[model]["last_seen"]:
                    models_data[model]["last_seen"] = span_time

        # Convert to sorted list (by request count descending)
        models_list = sorted(
            models_data.values(),
            key=lambda x: x["request_count"],
            reverse=True,
        )

        result = {
            "count": len(models_list),
            "models": models_list,
        }

        return json.dumps(result, indent=2)

    except Exception as e:
        return json.dumps({"error": f"Failed to list models: {str(e)}"})
