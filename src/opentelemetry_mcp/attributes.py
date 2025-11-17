"""Strongly-typed span attribute models following OpenTelemetry semantic conventions."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# Note: We import constants for documentation but must use string literals for Pydantic aliases
# due to mypy strict mode requirements
from .constants import GenAI


class SpanAttributes(BaseModel):
    """
    Strongly-typed span attributes following OpenTelemetry semantic conventions.

    Supports both gen_ai.* (OpenTelemetry standard) and llm.* (legacy Traceloop) naming conventions
    through field aliases. The primary access pattern uses gen_ai.* attributes.

    The model allows extra fields through ConfigDict(extra='allow') to support additional
    unknown attributes that may be present in span data.
    """

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    # LLM System and Model
    gen_ai_system: str | None = Field(None, alias="gen_ai.system")
    gen_ai_request_model: str | None = Field(None, alias="gen_ai.request.model")
    gen_ai_response_model: str | None = Field(None, alias="gen_ai.response.model")
    gen_ai_operation_name: str | None = Field(None, alias="gen_ai.operation.name")

    # Request Parameters
    gen_ai_request_temperature: float | None = Field(None, alias="gen_ai.request.temperature")
    gen_ai_request_top_p: float | None = Field(None, alias="gen_ai.request.top_p")
    gen_ai_request_max_tokens: int | None = Field(None, alias="gen_ai.request.max_tokens")
    gen_ai_request_is_streaming: bool | None = Field(None, alias="gen_ai.request.is_streaming")

    # Response Attributes
    gen_ai_response_finish_reasons: list[str] | None = Field(
        None, alias="gen_ai.response.finish_reasons"
    )

    # Usage Metrics (gen_ai.* format)
    gen_ai_usage_prompt_tokens: int | None = Field(None, alias="gen_ai.usage.prompt_tokens")
    gen_ai_usage_input_tokens: int | None = Field(None, alias="gen_ai.usage.input_tokens")
    gen_ai_usage_completion_tokens: int | None = Field(None, alias="gen_ai.usage.completion_tokens")
    gen_ai_usage_output_tokens: int | None = Field(None, alias="gen_ai.usage.output_tokens")
    gen_ai_usage_total_tokens: int | None = Field(None, alias="gen_ai.usage.total_tokens")

    # Legacy llm.* attributes (for backward compatibility with Traceloop)
    llm_vendor: str | None = Field(None, alias="llm.vendor")
    llm_request_model: str | None = Field(None, alias="llm.request.model")
    llm_response_finish_reasons: list[str] | None = Field(None, alias="llm.response.finish_reasons")
    llm_usage_prompt_tokens: int | None = Field(None, alias="llm.usage.prompt_tokens")
    llm_usage_input_tokens: int | None = Field(None, alias="llm.usage.input_tokens")
    llm_usage_completion_tokens: int | None = Field(None, alias="llm.usage.completion_tokens")
    llm_usage_output_tokens: int | None = Field(None, alias="llm.usage.output_tokens")
    llm_usage_total_tokens: int | None = Field(None, alias="llm.usage.total_tokens")

    # OpenTelemetry Standard Attributes
    service_name: str | None = Field(None, alias="service.name")
    otel_status_code: str | None = Field(None, alias="otel.status_code")
    error: bool | None = None

    def to_dict(self) -> dict[str, str | int | float | bool]:
        """
        Convert to dictionary representation with dotted keys.

        Returns only non-None values with their original dotted notation (e.g., "gen_ai.system").
        """
        result: dict[str, str | int | float | bool] = {}

        # Map field names back to their aliases for proper serialization
        for field_name, field_info in self.__class__.model_fields.items():
            value = getattr(self, field_name)
            if value is not None:
                # Use the alias if available, otherwise use field name
                key = field_info.alias or field_name
                result[key] = value

        # Add extra fields that were allowed through ConfigDict(extra='allow')
        if hasattr(self, "__pydantic_extra__") and self.__pydantic_extra__:
            for key, value in self.__pydantic_extra__.items():
                if value is not None:
                    result[key] = value

        return result

    def get(
        self, key: str, default: str | int | float | bool | None = None
    ) -> str | int | float | bool | None:
        """
        Get attribute value by key, supporting both dotted notation and field names.

        This method provides backward compatibility with dict-style access patterns.

        Args:
            key: Attribute key (e.g., "gen_ai.system" or "gen_ai_system")
            default: Default value if key not found

        Returns:
            Attribute value or default
        """
        # Try direct field access first (underscore notation)
        field_name = key.replace(".", "_")
        if hasattr(self, field_name):
            value = getattr(self, field_name)
            if value is not None:
                # Cast to ensure the return type matches the signature
                return value  # type: ignore[no-any-return]

        # Try extra fields (dotted notation)
        if (
            hasattr(self, "__pydantic_extra__")
            and self.__pydantic_extra__
            and key in self.__pydantic_extra__
        ):
            return self.__pydantic_extra__[key]  # type: ignore[no-any-return]

        return default

    def __getitem__(self, key: str) -> str | int | float | bool:
        """
        Get attribute value using subscript notation for backward compatibility.

        Args:
            key: Attribute key (e.g., "gen_ai.system")

        Returns:
            Attribute value

        Raises:
            KeyError: If key not found
        """
        value = self.get(key)
        if value is None:
            raise KeyError(key)
        return value


class SpanEvent(BaseModel):
    """
    Strongly-typed span event structure.

    Represents an event that occurred during span execution, such as prompt content
    or completion results in LLM operations.
    """

    model_config = ConfigDict(extra="allow")

    name: str = Field(
        ...,
        description=f"Event name (e.g., '{GenAI.EVENT_CONTENT_PROMPT}', '{GenAI.EVENT_CONTENT_COMPLETION}')",
    )
    timestamp: int = Field(..., description="Unix timestamp in nanoseconds")
    attributes: dict[str, str | int | float | bool] = Field(
        default_factory=dict, description="Event attributes with typed values"
    )


class HealthCheckResponse(BaseModel):
    """Health check response from backend systems."""

    status: Literal["healthy", "unhealthy"] = Field(..., description="Health status of the backend")
    backend: Literal["jaeger", "tempo", "traceloop"] = Field(..., description="Backend type")
    url: str = Field(..., description="Backend URL")
    error: str | None = Field(default=None, description="Error message if unhealthy")

    # Backend-specific fields
    service_count: int | None = Field(
        default=None, description="Number of services available (Jaeger)"
    )
    project_id: str | None = Field(default=None, description="Project ID (Traceloop)")
