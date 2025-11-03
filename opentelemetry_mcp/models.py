"""Data models for OpenTelemetry traces and Opentelemetry conventions."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from .attributes import SpanAttributes, SpanEvent


class SpanData(BaseModel):
    """OpenTelemetry span data."""

    trace_id: str
    span_id: str
    parent_span_id: str | None = None
    operation_name: str
    service_name: str
    start_time: datetime
    duration_ms: float
    status: Literal["OK", "ERROR", "UNSET"] = "UNSET"
    attributes: SpanAttributes = Field(default_factory=SpanAttributes)  # type: ignore[arg-type]
    events: list[SpanEvent] = Field(default_factory=list)

    @property
    def is_llm_span(self) -> bool:
        """Check if this span represents an LLM operation."""
        return self.attributes.gen_ai_system is not None

    @property
    def gen_ai_system(self) -> str | None:
        """Get the LLM provider (openai, anthropic, etc.)."""
        return self.attributes.gen_ai_system

    @property
    def gen_ai_model(self) -> str | None:
        """Get the LLM model name."""
        return self.attributes.gen_ai_request_model or self.attributes.gen_ai_response_model

    @property
    def has_error(self) -> bool:
        """Check if span has an error status."""
        return self.status == "ERROR"


class LLMSpanAttributes(BaseModel):
    """Parsed Opentelemetry (gen_ai.*) span attributes."""

    system: str  # Provider: openai, anthropic, etc.
    request_model: str | None = None
    response_model: str | None = None
    operation_name: str | None = None

    # Request parameters
    temperature: float | None = None
    top_p: float | None = None
    max_tokens: int | None = None
    is_streaming: bool = False

    # Usage metrics
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None

    # Prompts and completions (abbreviated in summary)
    prompt_preview: str | None = None
    completion_preview: str | None = None

    @classmethod
    def from_span(cls, span: SpanData) -> "LLMSpanAttributes | None":
        """Extract Opentelemetry attributes from a span."""
        if not span.is_llm_span:
            return None

        attrs = span.attributes

        # Handle different token naming conventions (OpenAI vs Anthropic)
        prompt_tokens = (
            attrs.gen_ai_usage_prompt_tokens
            or attrs.gen_ai_usage_input_tokens
            or attrs.llm_usage_prompt_tokens
            or attrs.llm_usage_input_tokens
            or 0
        )
        completion_tokens = (
            attrs.gen_ai_usage_completion_tokens
            or attrs.gen_ai_usage_output_tokens
            or attrs.llm_usage_completion_tokens
            or attrs.llm_usage_output_tokens
            or 0
        )

        # Extract prompt preview from events or attributes
        prompt_preview = None
        completion_preview = None

        for event in span.events:
            if event.name == "gen_ai.content.prompt":
                prompt_content = event.attributes.get("gen_ai.prompt.0.content")
                if prompt_content and isinstance(prompt_content, str):
                    prompt_preview = (
                        prompt_content[:100] + "..."
                        if len(prompt_content) > 100
                        else prompt_content
                    )

            if event.name == "gen_ai.content.completion":
                completion_content = event.attributes.get("gen_ai.completion.0.content")
                if completion_content and isinstance(completion_content, str):
                    completion_preview = (
                        completion_content[:100] + "..."
                        if len(completion_content) > 100
                        else completion_content
                    )

        # System is required, so we can safely assert it exists
        system = attrs.gen_ai_system
        if not system:
            return None

        return cls(
            system=system,
            request_model=attrs.gen_ai_request_model,
            response_model=attrs.gen_ai_response_model,
            operation_name=attrs.gen_ai_operation_name,
            temperature=attrs.gen_ai_request_temperature,
            top_p=attrs.gen_ai_request_top_p,
            max_tokens=attrs.gen_ai_request_max_tokens,
            is_streaming=attrs.gen_ai_request_is_streaming or False,
            prompt_tokens=prompt_tokens if prompt_tokens else None,
            completion_tokens=completion_tokens if completion_tokens else None,
            total_tokens=attrs.gen_ai_usage_total_tokens,
            prompt_preview=prompt_preview,
            completion_preview=completion_preview,
        )


class UsageMetrics(BaseModel):
    """Aggregated LLM usage metrics."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    request_count: int = 0

    # Breakdown by model
    by_model: dict[str, "UsageMetrics"] = Field(default_factory=dict)

    # Breakdown by service
    by_service: dict[str, "UsageMetrics"] = Field(default_factory=dict)

    def add_span(self, span: SpanData, llm_attrs: LLMSpanAttributes) -> None:
        """Add token usage from a span."""
        self.prompt_tokens += llm_attrs.prompt_tokens or 0
        self.completion_tokens += llm_attrs.completion_tokens or 0
        self.total_tokens += llm_attrs.total_tokens or 0
        self.request_count += 1

        # Add to model breakdown
        model = llm_attrs.response_model or llm_attrs.request_model or "unknown"
        if model not in self.by_model:
            self.by_model[model] = UsageMetrics()
        self.by_model[model].prompt_tokens += llm_attrs.prompt_tokens or 0
        self.by_model[model].completion_tokens += llm_attrs.completion_tokens or 0
        self.by_model[model].total_tokens += llm_attrs.total_tokens or 0
        self.by_model[model].request_count += 1

        # Add to service breakdown
        service = span.service_name
        if service not in self.by_service:
            self.by_service[service] = UsageMetrics()
        self.by_service[service].prompt_tokens += llm_attrs.prompt_tokens or 0
        self.by_service[service].completion_tokens += llm_attrs.completion_tokens or 0
        self.by_service[service].total_tokens += llm_attrs.total_tokens or 0
        self.by_service[service].request_count += 1


class TraceData(BaseModel):
    """Complete trace with all spans."""

    trace_id: str
    spans: list[SpanData]
    start_time: datetime
    duration_ms: float
    service_name: str
    root_operation: str
    status: Literal["OK", "ERROR", "UNSET"] = "UNSET"

    @property
    def llm_spans(self) -> list[SpanData]:
        """Filter spans that are LLM operations."""
        return [span for span in self.spans if span.is_llm_span]

    @property
    def has_errors(self) -> bool:
        """Check if trace contains any error spans."""
        return any(span.has_error for span in self.spans)

    @property
    def total_llm_tokens(self) -> int:
        """Calculate total tokens used across all LLM spans."""
        total = 0
        for span in self.llm_spans:
            llm_attrs = LLMSpanAttributes.from_span(span)
            if llm_attrs and llm_attrs.total_tokens:
                total += llm_attrs.total_tokens
        return total


class TraceQuery(BaseModel):
    """Query parameters for searching traces."""

    service_name: str | None = None
    operation_name: str | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    min_duration_ms: int | None = Field(default=None, ge=0)
    max_duration_ms: int | None = Field(default=None, ge=0)
    tags: dict[str, str] = Field(default_factory=dict)
    limit: int = Field(default=100, ge=1, le=1000)
    has_error: bool | None = None

    # Opentelemetry-specific filters
    gen_ai_system: str | None = None  # Filter by LLM provider
    gen_ai_model: str | None = None  # Filter by model name

    def to_backend_params(self) -> dict[str, str | int]:
        """Convert query to backend-specific parameters."""
        params: dict[str, str | int] = {}

        if self.service_name:
            params["service"] = self.service_name

        if self.operation_name:
            params["operation"] = self.operation_name

        if self.start_time:
            # Convert to microseconds since epoch (Jaeger format)
            params["start"] = int(self.start_time.timestamp() * 1_000_000)

        if self.end_time:
            params["end"] = int(self.end_time.timestamp() * 1_000_000)

        if self.min_duration_ms:
            params["minDuration"] = f"{self.min_duration_ms}ms"

        if self.max_duration_ms:
            params["maxDuration"] = f"{self.max_duration_ms}ms"

        params["limit"] = self.limit

        # Add tags including Opentelemetry filters
        all_tags = dict(self.tags)
        if self.gen_ai_system:
            all_tags["gen_ai.system"] = self.gen_ai_system
        if self.gen_ai_model:
            all_tags["gen_ai.request.model"] = self.gen_ai_model

        if all_tags:
            # Jaeger expects JSON-encoded tags
            import json

            params["tags"] = json.dumps(all_tags)

        return params


class TraceSummary(BaseModel):
    """Simplified trace summary for list results."""

    trace_id: str
    service_name: str
    operation_name: str
    start_time: datetime
    duration_ms: float
    status: Literal["OK", "ERROR", "UNSET"]
    span_count: int
    llm_span_count: int = 0
    total_tokens: int = 0
    has_errors: bool = False

    @classmethod
    def from_trace(cls, trace: TraceData) -> "TraceSummary":
        """Create summary from full trace data."""
        return cls(
            trace_id=trace.trace_id,
            service_name=trace.service_name,
            operation_name=trace.root_operation,
            start_time=trace.start_time,
            duration_ms=trace.duration_ms,
            status=trace.status,
            span_count=len(trace.spans),
            llm_span_count=len(trace.llm_spans),
            total_tokens=trace.total_llm_tokens,
            has_errors=trace.has_errors,
        )
