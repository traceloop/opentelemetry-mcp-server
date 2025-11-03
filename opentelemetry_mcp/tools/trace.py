"""Get trace tool implementation."""

import json
from typing import Any

from opentelemetry_mcp.backends.base import BaseBackend
from opentelemetry_mcp.models import LLMSpanAttributes


async def get_trace(backend: BaseBackend, trace_id: str) -> str:
    """Get complete trace details by trace ID.

    Args:
        backend: Backend instance to query
        trace_id: Trace identifier

    Returns:
        JSON string with complete trace data including all spans
    """
    try:
        # Fetch trace
        trace = await backend.get_trace(trace_id)

        # Build detailed response
        result: dict[str, Any] = {
            "trace_id": trace.trace_id,
            "service_name": trace.service_name,
            "root_operation": trace.root_operation,
            "start_time": trace.start_time.isoformat(),
            "duration_ms": trace.duration_ms,
            "status": trace.status,
            "span_count": len(trace.spans),
            "has_errors": trace.has_errors,
            "spans": [],
        }

        # Add span details
        spans: list[Any] = result["spans"]
        for span in trace.spans:
            span_data: dict[str, Any] = {
                "span_id": span.span_id,
                "parent_span_id": span.parent_span_id,
                "operation_name": span.operation_name,
                "service_name": span.service_name,
                "start_time": span.start_time.isoformat(),
                "duration_ms": span.duration_ms,
                "status": span.status,
                "attributes": span.attributes.to_dict(),
            }

            # If it's an LLM span, parse Opentelemetry attributes
            if span.is_llm_span:
                llm_attrs = LLMSpanAttributes.from_span(span)
                if llm_attrs:
                    span_data["llm_attributes"] = llm_attrs.model_dump(
                        mode="json", exclude_none=True
                    )

            spans.append(span_data)

        # Add LLM-specific summary
        if trace.llm_spans:
            result["llm_summary"] = {
                "llm_span_count": len(trace.llm_spans),
                "total_tokens": trace.total_llm_tokens,
                "models_used": list(
                    {
                        span.attributes.gen_ai_request_model
                        or span.attributes.gen_ai_response_model
                        for span in trace.llm_spans
                        if span.attributes.gen_ai_request_model
                        or span.attributes.gen_ai_response_model
                    }
                ),
            }

        return json.dumps(result, indent=2, default=str)

    except Exception as e:
        return json.dumps({"error": f"Failed to fetch trace: {str(e)}"})
