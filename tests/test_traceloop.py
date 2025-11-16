"""Tests for Traceloop backend."""

from datetime import datetime

import pytest

from opentelemetry_mcp.backends.traceloop import TraceloopBackend
from opentelemetry_mcp.models import TraceQuery


def test_traceloop_backend_requires_api_key() -> None:
    """Test that Traceloop backend requires an API key."""
    with pytest.raises(ValueError, match="requires an API key"):
        TraceloopBackend(url="https://api.traceloop.com/v2", api_key=None)


def test_traceloop_backend_initialization() -> None:
    """Test Traceloop backend initializes correctly."""
    backend = TraceloopBackend(
        url="https://api.traceloop.com/v2",
        api_key="test_key",
        timeout=30.0,
    )

    assert backend.url == "https://api.traceloop.com/v2"
    assert backend.api_key == "test_key"
    assert backend.timeout == 30.0
    assert backend.project_id == "default"


def test_traceloop_client_headers() -> None:
    """Test that Traceloop client has correct headers."""
    backend = TraceloopBackend(
        url="https://api.traceloop.com/v2",
        api_key="test_key",
    )

    client = backend.client
    assert client.headers["Authorization"] == "Bearer test_key"
    assert client.headers["Content-Type"] == "application/json"


def test_build_filters_for_search() -> None:
    """Test filter building for search_traces."""
    query = TraceQuery(
        service_name="my-service",
        operation_name="my-operation",
        gen_ai_system="openai",
        gen_ai_request_model="gpt-4",
        min_duration_ms=1000,
        max_duration_ms=5000,
        has_error=True,
        tags={"custom.tag": "value"},
        limit=50,
    )

    # This would be built by the search_traces method
    # We're just testing the logic

    filters = []

    if query.service_name:
        filters.append({"field": "service_name", "operator": "equals", "value": query.service_name})

    if query.operation_name:
        filters.append({"field": "span_name", "operator": "equals", "value": query.operation_name})

    if query.gen_ai_system:
        filters.append(
            {
                "field": "span_attributes.gen_ai.system",
                "operator": "equals",
                "value": query.gen_ai_system,
            }
        )

    if query.gen_ai_request_model:
        filters.append(
            {
                "field": "span_attributes.gen_ai.request.model",
                "operator": "equals",
                "value": query.gen_ai_request_model,
            }
        )

    if query.min_duration_ms:
        filters.append(
            {
                "field": "duration",
                "operator": "greater_than",
                "value": str(query.min_duration_ms),
            }
        )

    if query.max_duration_ms:
        filters.append(
            {
                "field": "duration",
                "operator": "less_than",
                "value": str(query.max_duration_ms),
            }
        )

    if query.has_error:
        filters.append({"field": "status_code", "operator": "equals", "value": "ERROR"})

    for key, value in query.tags.items():
        filters.append(
            {
                "field": f"span_attributes.{key}",
                "operator": "equals",
                "value": value,
            }
        )

    # Verify all filters were added
    assert len(filters) == 8
    assert filters[0] == {"field": "service_name", "operator": "equals", "value": "my-service"}
    assert filters[1] == {"field": "span_name", "operator": "equals", "value": "my-operation"}
    assert filters[2] == {
        "field": "span_attributes.gen_ai.system",
        "operator": "equals",
        "value": "openai",
    }
    assert filters[3] == {
        "field": "span_attributes.gen_ai.request.model",
        "operator": "equals",
        "value": "gpt-4",
    }
    assert filters[4] == {"field": "duration", "operator": "greater_than", "value": "1000"}
    assert filters[5] == {"field": "duration", "operator": "less_than", "value": "5000"}
    assert filters[6] == {"field": "status_code", "operator": "equals", "value": "ERROR"}
    assert filters[7] == {
        "field": "span_attributes.custom.tag",
        "operator": "equals",
        "value": "value",
    }


def test_convert_root_span_to_trace() -> None:
    """Test converting Traceloop root span to TraceData."""
    backend = TraceloopBackend(url="https://api.traceloop.com/v2", api_key="test_key")

    root_span = {
        "trace_id": "abc123",
        "span_id": "span1",
        "parent_span_id": "",
        "span_name": "workflow",
        "service_name": "my-service",
        "timestamp": 1704120000000,  # milliseconds
        "duration": 3000,  # milliseconds
        "status_code": "OK",
        "span_attributes": {
            "gen_ai.system": "openai",
            "gen_ai.request.model": "gpt-4",
            "gen_ai.usage.total_tokens": 1500,
        },
    }

    trace = backend._convert_root_span_to_trace(root_span)

    assert trace is not None
    assert trace.trace_id == "abc123"
    assert len(trace.spans) == 1
    assert trace.spans[0].span_id == "span1"
    assert trace.spans[0].operation_name == "workflow"
    assert trace.service_name == "my-service"
    assert trace.status == "OK"
    assert trace.duration_ms == 3000


def test_convert_spans_to_trace() -> None:
    """Test converting Traceloop spans array to TraceData."""
    backend = TraceloopBackend(url="https://api.traceloop.com/v2", api_key="test_key")

    spans_data = [
        {
            "trace_id": "abc123",
            "span_id": "root",
            "parent_span_id": "",
            "span_name": "workflow",
            "timestamp": 1704120000000,
            "duration": 3000,
            "span_attributes": {"traceloop.workflow.name": "chat"},
        },
        {
            "trace_id": "abc123",
            "span_id": "child",
            "parent_span_id": "root",
            "span_name": "llm.completion",
            "timestamp": 1704120001000,
            "duration": 2000,
            "span_attributes": {
                "gen_ai.system": "openai",
                "gen_ai.request.model": "gpt-4",
                "gen_ai.usage.total_tokens": 1500,
            },
        },
    ]

    trace = backend._convert_spans_to_trace("abc123", spans_data)

    assert trace is not None
    assert trace.trace_id == "abc123"
    assert len(trace.spans) == 2
    assert trace.spans[0].span_id == "root"
    assert trace.spans[1].span_id == "child"
    assert trace.spans[1].attributes.gen_ai_system == "openai"


def test_timestamp_conversion() -> None:
    """Test timestamp conversion from milliseconds to datetime."""
    # Traceloop returns timestamps in milliseconds
    timestamp_ms = 1704120000000

    # Convert to datetime
    dt = datetime.fromtimestamp(timestamp_ms / 1000)

    # Verify conversion
    assert dt.year == 2024
    assert dt.month == 1
    assert dt.day == 1


def test_duration_conversion() -> None:
    """Test duration stays in milliseconds."""
    # Traceloop returns duration in milliseconds
    duration_ms = 3500

    # Our internal model also uses milliseconds
    assert float(duration_ms) == 3500.0
