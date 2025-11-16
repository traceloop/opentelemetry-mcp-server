"""Find error traces tool implementation."""

import json
from typing import Any

from pydantic import ValidationError

from opentelemetry_mcp.backends.base import BaseBackend
from opentelemetry_mcp.models import TraceQuery, TraceSummary
from opentelemetry_mcp.utils import parse_iso_timestamp


async def find_errors(
    backend: BaseBackend,
    start_time: str | None = None,
    end_time: str | None = None,
    service_name: str | None = None,
    limit: int = 100,
) -> str:
    """Find traces with errors.

    Args:
        backend: Backend instance to query
        start_time: Start time (ISO 8601 format)
        end_time: End time (ISO 8601 format)
        service_name: Filter by service name
        limit: Maximum number of error traces to return

    Returns:
        JSON string with error traces including error details
    """
    # Parse timestamps
    start_dt, error = parse_iso_timestamp(start_time, "start_time")
    if error:
        return json.dumps({"error": error})

    end_dt, error = parse_iso_timestamp(end_time, "end_time")
    if error:
        return json.dumps({"error": error})

    # Build query with error filter
    try:
        query = TraceQuery(
            service_name=service_name,
            start_time=start_dt,
            end_time=end_dt,
            has_error=True,
            limit=limit,
        )
    except ValidationError as e:
        return json.dumps({"error": f"Invalid query parameters: {e}"})

    try:
        # Search for error traces
        traces = await backend.search_traces(query)

        # Build detailed error information
        error_traces = []

        for trace in traces:
            # Find error spans
            error_spans = [span for span in trace.spans if span.has_error]

            trace_info: dict[str, Any] = TraceSummary.from_trace(trace).model_dump(mode="json")

            # Add error details
            trace_info["error_spans"] = []
            error_spans_list: list[Any] = trace_info["error_spans"]
            for span in error_spans:
                error_info: dict[str, Any] = {
                    "span_id": span.span_id,
                    "operation_name": span.operation_name,
                    "service_name": span.service_name,
                    "status": span.status,
                }

                # Extract error message using typed attribute access
                error_message_val = (
                    span.attributes.get("error.message")
                    or span.attributes.get("exception.message")
                    or "Unknown error"
                )
                error_info["error_message"] = str(error_message_val)

                # Extract error type
                error_type_val = span.attributes.get("error.type") or span.attributes.get(
                    "exception.type"
                )
                if error_type_val:
                    error_info["error_type"] = str(error_type_val)

                # Extract stack trace (truncated)
                stack_trace_val = span.attributes.get("exception.stacktrace")
                if stack_trace_val:
                    # Truncate long stack traces
                    stack_trace_str = str(stack_trace_val)
                    if len(stack_trace_str) > 500:
                        error_info["stack_trace"] = stack_trace_str[:500] + "..."
                    else:
                        error_info["stack_trace"] = stack_trace_str

                # Check if it's an LLM-related error
                if span.is_llm_span:
                    error_info["is_llm_error"] = True
                    llm_provider = span.gen_ai_system
                    # Get model from request or response model
                    llm_model = (
                        span.attributes.gen_ai_request_model
                        or span.attributes.gen_ai_response_model
                    )
                    error_info["llm_provider"] = str(llm_provider) if llm_provider else None
                    error_info["llm_model"] = str(llm_model) if llm_model else None

                error_spans_list.append(error_info)

            error_traces.append(trace_info)

        result = {"count": len(error_traces), "error_traces": error_traces}

        return json.dumps(result, indent=2, default=str)

    except Exception as e:
        return json.dumps({"error": f"Failed to find error traces: {str(e)}"})
