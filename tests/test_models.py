"""Tests for data models."""

from datetime import datetime

from opentelemetry_mcp.attributes import SpanAttributes
from opentelemetry_mcp.models import LLMSpanAttributes, SpanData, TraceData, TraceQuery


def test_span_data_is_llm_span() -> None:
    """Test LLM span detection."""
    # LLM span
    llm_span = SpanData(
        trace_id="test",
        span_id="span1",
        operation_name="chat.completions",
        service_name="test",
        start_time=datetime.now(),
        duration_ms=100,
        attributes=SpanAttributes.model_validate({"gen_ai.system": "openai"}),
    )
    assert llm_span.is_llm_span is True

    # Non-LLM span
    regular_span = SpanData(
        trace_id="test",
        span_id="span2",
        operation_name="http.request",
        service_name="test",
        start_time=datetime.now(),
        duration_ms=50,
        attributes=SpanAttributes.model_validate({"http.method": "GET"}),
    )
    assert regular_span.is_llm_span is False


def test_llm_span_attributes_from_span() -> None:
    """Test extracting LLM attributes from span."""
    span = SpanData(
        trace_id="test",
        span_id="span1",
        operation_name="chat.completions",
        service_name="test",
        start_time=datetime.now(),
        duration_ms=100,
        attributes=SpanAttributes.model_validate(
            {
                "gen_ai.system": "openai",
                "gen_ai.request.model": "gpt-4",
                "gen_ai.usage.prompt_tokens": 150,
                "gen_ai.usage.completion_tokens": 300,
                "gen_ai.usage.total_tokens": 450,
            }
        ),
    )

    llm_attrs = LLMSpanAttributes.from_span(span)
    assert llm_attrs is not None
    assert llm_attrs.system == "openai"
    assert llm_attrs.request_model == "gpt-4"
    assert llm_attrs.prompt_tokens == 150
    assert llm_attrs.completion_tokens == 300
    assert llm_attrs.total_tokens == 450


def test_llm_span_attributes_anthropic_tokens() -> None:
    """Test handling Anthropic token naming (input_tokens vs prompt_tokens)."""
    span = SpanData(
        trace_id="test",
        span_id="span1",
        operation_name="anthropic.messages",
        service_name="test",
        start_time=datetime.now(),
        duration_ms=200,
        attributes=SpanAttributes.model_validate(
            {
                "gen_ai.system": "anthropic",
                "gen_ai.request.model": "claude-3-opus",
                "gen_ai.usage.input_tokens": 100,  # Anthropic uses input_tokens
                "gen_ai.usage.output_tokens": 200,  # Anthropic uses output_tokens
            }
        ),
    )

    llm_attrs = LLMSpanAttributes.from_span(span)
    assert llm_attrs is not None
    assert llm_attrs.system == "anthropic"
    assert llm_attrs.prompt_tokens == 100
    assert llm_attrs.completion_tokens == 200


def test_trace_data_llm_spans(sample_trace_data: TraceData) -> None:
    """Test filtering LLM spans from trace."""
    trace = sample_trace_data
    llm_spans = trace.llm_spans

    assert len(llm_spans) == 1
    assert llm_spans[0].is_llm_span is True


def test_trace_data_total_tokens(sample_trace_data: TraceData) -> None:
    """Test total token calculation."""
    trace = sample_trace_data
    total_tokens = trace.total_llm_tokens

    assert total_tokens == 300


def test_trace_query_to_backend_params() -> None:
    """Test converting TraceQuery to backend parameters."""
    query = TraceQuery(
        service_name="my-service",
        operation_name="my-operation",
        min_duration_ms=100,
        limit=50,
        gen_ai_system="openai",
        tags={"custom.tag": "value"},
    )

    params = query.to_backend_params()

    assert params["service"] == "my-service"
    assert params["operation"] == "my-operation"
    assert params["minDuration"] == "100ms"
    assert params["limit"] == 50
    tags = params["tags"]
    assert isinstance(tags, str)
    assert "openai" in tags
    assert "custom.tag" in tags
