"""Data models for OpenTelemetry traces and Opentelemetry conventions."""

from collections.abc import Sequence
from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from .attributes import SpanAttributes, SpanEvent
from .constants import Fields, GenAI, Service


class FilterOperator(str, Enum):
    """Supported filter operators for trace queries."""

    # String operators
    EQUALS = "equals"
    NOT_EQUALS = "not_equals"
    CONTAINS = "contains"
    NOT_CONTAINS = "not_contains"
    STARTS_WITH = "starts_with"
    ENDS_WITH = "ends_with"
    IN = "in"
    NOT_IN = "not_in"

    # Number operators
    GT = "gt"
    LT = "lt"
    GTE = "gte"
    LTE = "lte"
    BETWEEN = "between"

    # Existence operators
    EXISTS = "exists"
    NOT_EXISTS = "not_exists"


class FilterType(str, Enum):
    """Data types for filter values."""

    STRING = "string"
    NUMBER = "number"
    BOOLEAN = "boolean"


class Filter(BaseModel):
    """A single filter condition for trace queries."""

    field: str = Field(..., description="Field name in dotted notation (e.g., 'gen_ai.system')")
    operator: FilterOperator = Field(..., description="Comparison operator")
    value: str | int | float | bool | None = Field(
        default=None, description="Single value for most operators"
    )
    values: Sequence[str | int | float | bool] | None = Field(
        default=None, description="Multiple values for 'in', 'not_in', 'between' operators"
    )
    value_type: FilterType = Field(..., description="Type of the value(s)")

    @model_validator(mode="after")
    def validate_filter_values(self) -> "Filter":
        """Validate that value/values are provided correctly for the operator."""
        requires_multiple = self.operator in [
            FilterOperator.IN,
            FilterOperator.NOT_IN,
            FilterOperator.BETWEEN,
        ]
        requires_none = self.operator in [FilterOperator.EXISTS, FilterOperator.NOT_EXISTS]

        if requires_none:
            if self.value is not None or self.values is not None:
                raise ValueError(f"Operator '{self.operator}' does not accept value or values")
        elif requires_multiple:
            if not self.values:
                raise ValueError(f"Operator '{self.operator}' requires 'values' field")
            if self.operator == FilterOperator.BETWEEN and len(self.values) != 2:
                raise ValueError("Operator 'between' requires exactly 2 values")
        else:
            if self.value is None:
                raise ValueError(f"Operator '{self.operator}' requires 'value' field")

        return self


def _convert_params_to_filters(
    service_name: str | None = None,
    operation_name: str | None = None,
    min_duration_ms: int | None = None,
    max_duration_ms: int | None = None,
    has_error: bool | None = None,
    gen_ai_system: str | None = None,
    gen_ai_request_model: str | None = None,
    gen_ai_response_model: str | None = None,
    tags: dict[str, str] | None = None,
    explicit_filters: list[Filter] | None = None,
) -> list[Filter]:
    """Convert query parameters to Filter objects and combine with explicit filters.

    This helper function is used by both TraceQuery and SpanQuery to avoid code duplication.

    Args:
        service_name: Service name to filter by
        operation_name: Operation/span name to filter by
        min_duration_ms: Minimum duration in milliseconds
        max_duration_ms: Maximum duration in milliseconds
        has_error: Filter for error status (True=ERROR, False=NOT ERROR)
        gen_ai_system: LLM provider (openai, anthropic, etc.)
        gen_ai_request_model: Requested model name
        gen_ai_response_model: Actual model used in response
        tags: Custom tags to filter by (key-value pairs)
        explicit_filters: Explicit Filter objects to append

    Returns:
        Combined list of all filters (converted + explicit)
    """
    all_filters: list[Filter] = []

    # Convert parameters to filters
    if service_name:
        all_filters.append(
            Filter(
                field=Service.NAME,
                operator=FilterOperator.EQUALS,
                value=service_name,
                value_type=FilterType.STRING,
            )
        )

    if operation_name:
        all_filters.append(
            Filter(
                field=Fields.OPERATION_NAME,
                operator=FilterOperator.EQUALS,
                value=operation_name,
                value_type=FilterType.STRING,
            )
        )

    if min_duration_ms is not None:
        all_filters.append(
            Filter(
                field=Fields.DURATION,
                operator=FilterOperator.GTE,
                value=min_duration_ms,
                value_type=FilterType.NUMBER,
            )
        )

    if max_duration_ms:
        all_filters.append(
            Filter(
                field=Fields.DURATION,
                operator=FilterOperator.LTE,
                value=max_duration_ms,
                value_type=FilterType.NUMBER,
            )
        )

    if has_error is not None:
        if has_error:
            all_filters.append(
                Filter(
                    field=Fields.STATUS,
                    operator=FilterOperator.EQUALS,
                    value="ERROR",
                    value_type=FilterType.STRING,
                )
            )
        else:
            all_filters.append(
                Filter(
                    field=Fields.STATUS,
                    operator=FilterOperator.NOT_EQUALS,
                    value="ERROR",
                    value_type=FilterType.STRING,
                )
            )

    if gen_ai_system:
        all_filters.append(
            Filter(
                field=GenAI.SYSTEM,
                operator=FilterOperator.EQUALS,
                value=gen_ai_system,
                value_type=FilterType.STRING,
            )
        )

    if gen_ai_request_model:
        all_filters.append(
            Filter(
                field=GenAI.REQUEST_MODEL,
                operator=FilterOperator.EQUALS,
                value=gen_ai_request_model,
                value_type=FilterType.STRING,
            )
        )

    if gen_ai_response_model:
        all_filters.append(
            Filter(
                field=GenAI.RESPONSE_MODEL,
                operator=FilterOperator.EQUALS,
                value=gen_ai_response_model,
                value_type=FilterType.STRING,
            )
        )

    # Add custom tags as filters
    if tags:
        for key, value in tags.items():
            all_filters.append(
                Filter(
                    field=key,
                    operator=FilterOperator.EQUALS,
                    value=value,
                    value_type=FilterType.STRING,
                )
            )

    # Add explicit filters
    if explicit_filters:
        all_filters.extend(explicit_filters)

    return all_filters


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

    # Response attributes
    finish_reasons: list[str] | None = None

    # Usage metrics
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None

    # Prompts and completions (abbreviated in summary)
    prompt_preview: str | None = None
    completion_preview: str | None = None

    @classmethod
    def from_span(cls, span: SpanData) -> "LLMSpanAttributes | None":
        """Extract Opentelemetry attributes from a span with enhanced token calculation."""
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

        # Enhanced total_tokens calculation:
        # 1. Try explicit total_tokens attributes
        # 2. Sum all gen_ai.usage.* numeric attributes
        # 3. Fallback to prompt + completion
        total_tokens = attrs.gen_ai_usage_total_tokens or attrs.llm_usage_total_tokens

        if not total_tokens:
            # Search for all gen_ai.usage.* attributes and sum numeric values
            usage_sum = 0
            attrs_dict = attrs.to_dict()
            usage_prefix = "gen_ai.usage."
            for key, value in attrs_dict.items():
                if key.startswith(usage_prefix) and isinstance(value, int):
                    usage_sum += value

            # If we found usage attributes, use their sum
            if usage_sum > 0:
                total_tokens = usage_sum
            # Otherwise fallback to prompt + completion
            elif prompt_tokens or completion_tokens:
                total_tokens = prompt_tokens + completion_tokens

        # Parse finish_reasons (can be array or comma-separated string)
        finish_reasons = attrs.gen_ai_response_finish_reasons or attrs.llm_response_finish_reasons
        if finish_reasons is None:
            # Check if it's stored as a string in extra attributes
            finish_reasons_raw = attrs.get(GenAI.RESPONSE_FINISH_REASONS) or attrs.get(
                "llm.response.finish_reasons"
            )
            if isinstance(finish_reasons_raw, str):
                finish_reasons = [reason.strip() for reason in finish_reasons_raw.split(",")]
            elif isinstance(finish_reasons_raw, list):
                finish_reasons = finish_reasons_raw

        # Extract prompt preview from events or attributes
        prompt_preview = None
        completion_preview = None

        for event in span.events:
            if event.name == GenAI.EVENT_CONTENT_PROMPT:
                prompt_content = event.attributes.get(GenAI.EVENT_PROMPT_CONTENT)
                if prompt_content and isinstance(prompt_content, str):
                    prompt_preview = (
                        prompt_content[:100] + "..."
                        if len(prompt_content) > 100
                        else prompt_content
                    )

            if event.name == GenAI.EVENT_CONTENT_COMPLETION:
                completion_content = event.attributes.get(GenAI.EVENT_COMPLETION_CONTENT)
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
            finish_reasons=finish_reasons,
            prompt_tokens=prompt_tokens if prompt_tokens else None,
            completion_tokens=completion_tokens if completion_tokens else None,
            total_tokens=total_tokens if total_tokens else None,
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

    # Simple parameters
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
    gen_ai_request_model: str | None = None  # Filter by requested model
    gen_ai_response_model: str | None = None  # Filter by actual model used

    # New generic filter system
    filters: list[Filter] = Field(default_factory=list, description="Generic filter conditions")
    logical_operator: Literal["AND"] = Field(
        default="AND", description="Logical operator for combining filters (currently only AND)"
    )

    def has_filters(self) -> bool:
        """Check if any filters are specified."""
        return bool(
            self.service_name
            or self.operation_name
            or self.min_duration_ms
            or self.max_duration_ms
            or self.has_error
            or self.gen_ai_system
            or self.gen_ai_request_model
            or self.gen_ai_response_model
            or self.tags
            or self.filters
        )

    def get_all_filters(self) -> list[Filter]:
        """Convert parameters to Filter objects and combine with explicit filters.

        Returns:
            Combined list of all filters (converted + explicit)
        """
        return _convert_params_to_filters(
            service_name=self.service_name,
            operation_name=self.operation_name,
            min_duration_ms=self.min_duration_ms,
            max_duration_ms=self.max_duration_ms,
            has_error=self.has_error,
            gen_ai_system=self.gen_ai_system,
            gen_ai_request_model=self.gen_ai_request_model,
            gen_ai_response_model=self.gen_ai_response_model,
            tags=self.tags if self.tags else None,
            explicit_filters=self.filters,
        )

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
        if self.gen_ai_request_model:
            all_tags["gen_ai.request.model"] = self.gen_ai_request_model
        if self.gen_ai_response_model:
            all_tags["gen_ai.response.model"] = self.gen_ai_response_model

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


class SpanQuery(BaseModel):
    """Query parameters for searching individual spans."""

    # Basic filters
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
    gen_ai_system: str | None = None
    gen_ai_request_model: str | None = None
    gen_ai_response_model: str | None = None

    # Generic filter system
    filters: list[Filter] = Field(default_factory=list, description="Generic filter conditions")
    logical_operator: Literal["AND"] = Field(
        default="AND", description="Logical operator for combining filters (currently only AND)"
    )

    def has_filters(self) -> bool:
        """Check if any filters are specified."""
        return bool(
            self.service_name
            or self.operation_name
            or self.min_duration_ms
            or self.max_duration_ms
            or self.has_error
            or self.gen_ai_system
            or self.gen_ai_request_model
            or self.gen_ai_response_model
            or self.tags
            or self.filters
        )

    def get_all_filters(self) -> list[Filter]:
        """Convert parameters to Filter objects and combine with explicit filters.

        Returns:
            Combined list of all filters (converted + explicit)
        """
        return _convert_params_to_filters(
            service_name=self.service_name,
            operation_name=self.operation_name,
            min_duration_ms=self.min_duration_ms,
            max_duration_ms=self.max_duration_ms,
            has_error=self.has_error,
            gen_ai_system=self.gen_ai_system,
            gen_ai_request_model=self.gen_ai_request_model,
            gen_ai_response_model=self.gen_ai_response_model,
            tags=self.tags if self.tags else None,
            explicit_filters=self.filters,
        )


class SpanSummary(BaseModel):
    """Simplified span summary for list results."""

    trace_id: str
    span_id: str
    parent_span_id: str | None
    operation_name: str
    service_name: str
    start_time: datetime
    duration_ms: float
    status: Literal["OK", "ERROR", "UNSET"]
    is_llm_span: bool = False
    gen_ai_system: str | None = None
    total_tokens: int | None = None

    @classmethod
    def from_span(cls, span: SpanData) -> "SpanSummary":
        """Create summary from full span data."""
        llm_attrs = LLMSpanAttributes.from_span(span) if span.is_llm_span else None

        return cls(
            trace_id=span.trace_id,
            span_id=span.span_id,
            parent_span_id=span.parent_span_id,
            operation_name=span.operation_name,
            service_name=span.service_name,
            start_time=span.start_time,
            duration_ms=span.duration_ms,
            status=span.status,
            is_llm_span=span.is_llm_span,
            gen_ai_system=llm_attrs.system if llm_attrs else None,
            total_tokens=llm_attrs.total_tokens if llm_attrs else None,
        )
