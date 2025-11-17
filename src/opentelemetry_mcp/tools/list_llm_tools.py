"""List LLM tools tool implementation."""

import json
from datetime import datetime
from typing import Any

from opentelemetry.semconv_ai import TraceloopSpanKindValues
from pydantic import BaseModel

from opentelemetry_mcp.backends.base import BaseBackend
from opentelemetry_mcp.constants import Traceloop
from opentelemetry_mcp.models import Filter, FilterOperator, FilterType, SpanQuery
from opentelemetry_mcp.utils import parse_iso_timestamp


class LLMToolInfo(BaseModel):
    """Information about an LLM tool usage."""

    tool_name: str
    usage_count: int
    services: list[str]
    first_seen: datetime
    last_seen: datetime


async def list_llm_tools(
    backend: BaseBackend,
    start_time: str | None = None,
    end_time: str | None = None,
    service_name: str | None = None,
    gen_ai_system: str | None = None,
    limit: int = 1000,
) -> str:
    """List all LLM tools being used by identifying traceloop.span.kind == tool.

    Discovers which tools/functions LLM applications are calling, grouped by tool name
    with usage statistics.

    Args:
        backend: Backend instance to query
        start_time: Start time in ISO 8601 format
        end_time: End time in ISO 8601 format
        service_name: Filter by service name
        gen_ai_system: Filter by LLM provider (openai, anthropic, etc.)
        limit: Maximum spans to analyze (default: 1000)

    Returns:
        JSON string with list of tools and their statistics
    """
    # Parse timestamps
    start_dt, error = parse_iso_timestamp(start_time, "start_time")
    if error:
        return json.dumps({"error": error})

    end_dt, error = parse_iso_timestamp(end_time, "end_time")
    if error:
        return json.dumps({"error": error})

    # Build filter for traceloop.span.kind == tool
    filters = [
        Filter(
            field=Traceloop.SPAN_KIND,
            operator=FilterOperator.EQUALS,
            value=TraceloopSpanKindValues.TOOL.value,
            value_type=FilterType.STRING,
        )
    ]

    # Build query
    query = SpanQuery(
        service_name=service_name,
        start_time=start_dt,
        end_time=end_dt,
        gen_ai_system=gen_ai_system,
        filters=filters,
        limit=limit,
    )

    try:
        # Execute search
        spans = await backend.search_spans(query)

        if not spans:
            return json.dumps(
                {
                    "count": 0,
                    "tools": [],
                    "message": "No LLM tool spans found matching the criteria",
                }
            )

        # Group spans by tool name (using operation_name as tool name)
        tools_map: dict[str, dict[str, Any]] = {}

        for span in spans:
            tool_name = span.operation_name

            if tool_name not in tools_map:
                tools_map[tool_name] = {
                    "tool_name": tool_name,
                    "usage_count": 0,
                    "services": set(),
                    "first_seen": span.start_time,
                    "last_seen": span.start_time,
                }

            tool_data = tools_map[tool_name]
            tool_data["usage_count"] += 1
            tool_data["services"].add(span.service_name)

            # Update time bounds
            if span.start_time < tool_data["first_seen"]:
                tool_data["first_seen"] = span.start_time
            if span.start_time > tool_data["last_seen"]:
                tool_data["last_seen"] = span.start_time

        # Convert to list and serialize
        tools_list = []
        for tool_data in tools_map.values():
            # Convert set to sorted list
            tool_data["services"] = sorted(list(tool_data["services"]))
            tool_info = LLMToolInfo(**tool_data)
            tools_list.append(tool_info.model_dump(mode="json"))

        # Sort by usage count descending
        tools_list.sort(key=lambda x: x["usage_count"], reverse=True)

        result = {
            "count": len(tools_list),
            "total_calls": sum(t["usage_count"] for t in tools_list),
            "tools": tools_list,
        }

        return json.dumps(result, indent=2, default=str)

    except Exception as e:
        return json.dumps({"error": f"Failed to list LLM tools: {str(e)}"})
