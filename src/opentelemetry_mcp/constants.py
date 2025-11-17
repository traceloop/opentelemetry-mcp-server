"""
Semantic conventions for OpenTelemetry attributes.

This module centralizes all OpenTelemetry semantic convention constants used throughout
the codebase. It imports from:
- opentelemetry.semconv_ai: Traceloop and LLM-specific conventions (OpenLLMetry)
- opentelemetry.semconv.trace: Standard OpenTelemetry conventions

By using these constants instead of magic strings, we ensure:
- Type safety and IDE autocomplete
- Consistency with OpenLLMetry ecosystem
- Easier refactoring and maintenance
- Alignment with semantic convention standards
"""

# Import OpenLLMetry semantic conventions (Traceloop/LLM-specific)
# Import standard OpenTelemetry semantic conventions
from opentelemetry.semconv import resource
from opentelemetry.semconv.trace import SpanAttributes as OtelSpanAttributes
from opentelemetry.semconv_ai import (
    EventAttributes,
    Events,
    GenAISystem,
    LLMRequestTypeValues,
    Meters,
    SpanAttributes,
    TraceloopSpanKindValues,
)


# Gen AI attributes are not yet in the standard package, so we define them ourselves
# These follow the OpenTelemetry AI semantic conventions specification
class GenAIAttributes:
    """Gen AI semantic conventions (incubating)."""

    # System and model
    GEN_AI_SYSTEM = "gen_ai.system"
    GEN_AI_REQUEST_MODEL = "gen_ai.request.model"
    GEN_AI_RESPONSE_MODEL = "gen_ai.response.model"
    GEN_AI_OPERATION_NAME = "gen_ai.operation.name"

    # Request parameters
    GEN_AI_REQUEST_TEMPERATURE = "gen_ai.request.temperature"
    GEN_AI_REQUEST_TOP_P = "gen_ai.request.top_p"
    GEN_AI_REQUEST_MAX_TOKENS = "gen_ai.request.max_tokens"
    GEN_AI_REQUEST_IS_STREAMING = "gen_ai.request.is_streaming"

    # Response
    GEN_AI_RESPONSE_FINISH_REASONS = "gen_ai.response.finish_reasons"

    # Usage/tokens
    GEN_AI_USAGE_PROMPT_TOKENS = "gen_ai.usage.prompt_tokens"
    GEN_AI_USAGE_INPUT_TOKENS = "gen_ai.usage.input_tokens"
    GEN_AI_USAGE_COMPLETION_TOKENS = "gen_ai.usage.completion_tokens"
    GEN_AI_USAGE_OUTPUT_TOKENS = "gen_ai.usage.output_tokens"
    GEN_AI_USAGE_TOTAL_TOKENS = "gen_ai.usage.total_tokens"


# Re-export all for convenience
__all__ = [
    # Enums
    "GenAISystem",
    "TraceloopSpanKindValues",
    "LLMRequestTypeValues",
    "Events",
    "EventAttributes",
    "Meters",
    # Attribute classes
    "SpanAttributes",
    "OtelSpanAttributes",
]


# Commonly used attribute constants (for backwards compatibility and convenience)
class GenAI:
    """Gen AI semantic conventions namespace."""

    # System and model
    SYSTEM = GenAIAttributes.GEN_AI_SYSTEM
    REQUEST_MODEL = GenAIAttributes.GEN_AI_REQUEST_MODEL
    RESPONSE_MODEL = GenAIAttributes.GEN_AI_RESPONSE_MODEL
    OPERATION_NAME = GenAIAttributes.GEN_AI_OPERATION_NAME

    # Request parameters
    REQUEST_TEMPERATURE = GenAIAttributes.GEN_AI_REQUEST_TEMPERATURE
    REQUEST_TOP_P = GenAIAttributes.GEN_AI_REQUEST_TOP_P
    REQUEST_MAX_TOKENS = GenAIAttributes.GEN_AI_REQUEST_MAX_TOKENS
    REQUEST_IS_STREAMING = GenAIAttributes.GEN_AI_REQUEST_IS_STREAMING

    # Response
    RESPONSE_FINISH_REASONS = GenAIAttributes.GEN_AI_RESPONSE_FINISH_REASONS

    # Usage/tokens
    USAGE_PROMPT_TOKENS = GenAIAttributes.GEN_AI_USAGE_PROMPT_TOKENS
    USAGE_INPUT_TOKENS = GenAIAttributes.GEN_AI_USAGE_INPUT_TOKENS
    USAGE_COMPLETION_TOKENS = GenAIAttributes.GEN_AI_USAGE_COMPLETION_TOKENS
    USAGE_OUTPUT_TOKENS = GenAIAttributes.GEN_AI_USAGE_OUTPUT_TOKENS
    USAGE_TOTAL_TOKENS = GenAIAttributes.GEN_AI_USAGE_TOTAL_TOKENS

    # Cache tokens (Anthropic prompt caching)
    # Note: OpenLLMetry has these as GEN_AI_USAGE_CACHE_* string values
    USAGE_CACHE_CREATION_INPUT_TOKENS = "gen_ai.usage.cache_creation_input_tokens"
    USAGE_CACHE_READ_INPUT_TOKENS = "gen_ai.usage.cache_read_input_tokens"

    # Event names
    EVENT_CONTENT_PROMPT = "gen_ai.content.prompt"
    EVENT_CONTENT_COMPLETION = "gen_ai.content.completion"

    # Event attribute names
    EVENT_PROMPT_CONTENT = "gen_ai.prompt.0.content"
    EVENT_COMPLETION_CONTENT = "gen_ai.completion.0.content"


class LegacyLLM:
    """Legacy LLM semantic conventions (for backward compatibility)."""

    # System and model
    VENDOR = "llm.vendor"
    REQUEST_MODEL = SpanAttributes.LLM_REQUEST_MODEL
    RESPONSE_MODEL = "llm.response.model"

    # Request
    REQUEST_TYPE = SpanAttributes.LLM_REQUEST_TYPE
    IS_STREAMING = SpanAttributes.LLM_IS_STREAMING
    TEMPERATURE = "llm.temperature"
    TOP_P = SpanAttributes.LLM_TOP_K
    MAX_TOKENS = "llm.max_tokens"
    FREQUENCY_PENALTY = SpanAttributes.LLM_FREQUENCY_PENALTY
    PRESENCE_PENALTY = SpanAttributes.LLM_PRESENCE_PENALTY

    # Response
    RESPONSE_FINISH_REASON = SpanAttributes.LLM_RESPONSE_FINISH_REASON
    RESPONSE_FINISH_REASONS = "llm.response.finish_reasons"

    # Usage/tokens
    USAGE_TOTAL_TOKENS = SpanAttributes.LLM_USAGE_TOTAL_TOKENS
    USAGE_PROMPT_TOKENS = "llm.usage.prompt_tokens"
    USAGE_INPUT_TOKENS = "llm.usage.input_tokens"
    USAGE_COMPLETION_TOKENS = "llm.usage.completion_tokens"
    USAGE_OUTPUT_TOKENS = "llm.usage.output_tokens"


class Traceloop:
    """Traceloop-specific semantic conventions."""

    # Span classification
    SPAN_KIND = SpanAttributes.TRACELOOP_SPAN_KIND

    # Workflow
    WORKFLOW_NAME = SpanAttributes.TRACELOOP_WORKFLOW_NAME

    # Entity tracking
    ENTITY_NAME = SpanAttributes.TRACELOOP_ENTITY_NAME
    ENTITY_PATH = SpanAttributes.TRACELOOP_ENTITY_PATH
    ENTITY_VERSION = SpanAttributes.TRACELOOP_ENTITY_VERSION
    ENTITY_INPUT = SpanAttributes.TRACELOOP_ENTITY_INPUT
    ENTITY_OUTPUT = SpanAttributes.TRACELOOP_ENTITY_OUTPUT

    # Association
    ASSOCIATION_PROPERTIES = SpanAttributes.TRACELOOP_ASSOCIATION_PROPERTIES

    # Prompt management
    PROMPT_MANAGED = SpanAttributes.TRACELOOP_PROMPT_MANAGED
    PROMPT_KEY = SpanAttributes.TRACELOOP_PROMPT_KEY
    PROMPT_VERSION = SpanAttributes.TRACELOOP_PROMPT_VERSION
    PROMPT_VERSION_NAME = SpanAttributes.TRACELOOP_PROMPT_VERSION_NAME
    PROMPT_VERSION_HASH = SpanAttributes.TRACELOOP_PROMPT_VERSION_HASH
    PROMPT_TEMPLATE = SpanAttributes.TRACELOOP_PROMPT_TEMPLATE
    PROMPT_TEMPLATE_VARIABLES = SpanAttributes.TRACELOOP_PROMPT_TEMPLATE_VARIABLES


class Service:
    """Service resource attributes."""

    NAME = resource.ResourceAttributes.SERVICE_NAME
    VERSION = resource.ResourceAttributes.SERVICE_VERSION


class Status:
    """OpenTelemetry status attributes."""

    CODE = OtelSpanAttributes.OTEL_STATUS_CODE


# Field name constants for common operations
class Fields:
    """Common field names used in queries and filters."""

    SERVICE_NAME = Service.NAME
    DURATION = "duration"
    STATUS = "status"
    TRACE_ID = "trace_id"
    SPAN_ID = "span_id"
    PARENT_SPAN_ID = "parent_span_id"
    OPERATION_NAME = "operation_name"
    START_TIME = "start_time"
