"""Pytest configuration and fixtures."""

from typing import Any

import pytest
from pydantic import HttpUrl

from opentelemetry_mcp.attributes import SpanAttributes
from opentelemetry_mcp.config import BackendConfig
from opentelemetry_mcp.models import SpanData, TraceData


@pytest.fixture
def sample_span_data() -> dict[str, Any]:
    """Sample Jaeger span data for testing."""
    return {
        "traceID": "abc123",
        "spanID": "span1",
        "operationName": "test_operation",
        "startTime": 1234567890000000,  # microseconds
        "duration": 5000000,  # microseconds (5s)
        "tags": [
            {"key": "gen_ai.system", "value": "openai"},
            {"key": "gen_ai.request.model", "value": "gpt-4"},
            {"key": "gen_ai.usage.prompt_tokens", "value": 100},
            {"key": "gen_ai.usage.completion_tokens", "value": 200},
            {"key": "gen_ai.usage.total_tokens", "value": 300},
        ],
        "process": {"serviceName": "test-service"},
        "references": [],
        "logs": [],
    }


@pytest.fixture
def sample_trace_data() -> TraceData:
    """Sample TraceData for testing."""
    from datetime import datetime

    span = SpanData(
        trace_id="abc123",
        span_id="span1",
        parent_span_id=None,
        operation_name="test_operation",
        service_name="test-service",
        start_time=datetime.now(),
        duration_ms=5000,
        status="OK",
        attributes=SpanAttributes.model_validate(
            {
                "gen_ai.system": "openai",
                "gen_ai.request.model": "gpt-4",
                "gen_ai.usage.prompt_tokens": 100,
                "gen_ai.usage.completion_tokens": 200,
                "gen_ai.usage.total_tokens": 300,
            }
        ),
    )

    return TraceData(
        trace_id="abc123",
        spans=[span],
        start_time=span.start_time,
        duration_ms=5000,
        service_name="test-service",
        root_operation="test_operation",
        status="OK",
    )


@pytest.fixture
def jaeger_backend_config() -> BackendConfig:
    """Jaeger backend configuration for testing."""
    return BackendConfig(
        type="jaeger",
        url=HttpUrl("http://localhost:16686"),
        timeout=5.0,
    )
