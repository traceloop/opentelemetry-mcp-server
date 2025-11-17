"""Configuration management for Opentelemetry MCP Server."""

import logging
import os
from typing import Literal

from dotenv import load_dotenv
from pydantic import BaseModel, Field, HttpUrl, TypeAdapter, field_validator

logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()


class BackendConfig(BaseModel):
    """Configuration for OpenTelemetry trace backend."""

    type: Literal["jaeger", "tempo", "traceloop"]
    url: HttpUrl
    api_key: str | None = Field(default=None, exclude=True)
    timeout: float = Field(default=30.0, gt=0, le=300)
    environments: list[str] = Field(default_factory=lambda: ["prd"])

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: HttpUrl) -> HttpUrl:
        """Validate URL scheme."""
        if v.scheme not in ["http", "https"]:
            raise ValueError("URL must use http or https scheme")
        return v

    @classmethod
    def from_env(cls) -> "BackendConfig":
        """Load configuration from environment variables."""
        backend_type = os.getenv("BACKEND_TYPE", "jaeger")
        backend_url = os.getenv("BACKEND_URL", "http://localhost:16686")
        if backend_type not in ["jaeger", "tempo", "traceloop"]:
            raise ValueError(
                f"Invalid BACKEND_TYPE: {backend_type}. Must be one of: jaeger, tempo, traceloop"
            )

        # Parse environments from comma-separated string
        environments_str = os.getenv("BACKEND_ENVIRONMENTS", "prd")
        environments = [env.strip() for env in environments_str.split(",") if env.strip()]

        # Parse timeout with validation
        timeout_str = os.getenv("BACKEND_TIMEOUT", "30")
        try:
            timeout = float(timeout_str)
        except (ValueError, TypeError) as e:
            logger.warning(f"Invalid BACKEND_TIMEOUT value '{timeout_str}': {e}. Using default: 30")
            timeout = 30.0

        return cls(
            type=backend_type,  # type: ignore
            url=backend_url,  # type: ignore
            api_key=os.getenv("BACKEND_API_KEY"),
            timeout=timeout,
            environments=environments,
        )


class ServerConfig(BaseModel):
    """MCP Server configuration."""

    backend: BackendConfig
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    max_traces_per_query: int = Field(default=500, ge=1, le=1000)

    @classmethod
    def from_env(cls) -> "ServerConfig":
        """Load server configuration from environment variables."""
        log_level_str = os.getenv("LOG_LEVEL", "INFO").upper()
        valid_levels = ("DEBUG", "INFO", "WARNING", "ERROR")
        log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = (
            log_level_str if log_level_str in valid_levels else "INFO"  # type: ignore[assignment]
        )

        # Parse max_traces_per_query with validation
        max_traces_str = os.getenv("MAX_TRACES_PER_QUERY", "500")
        try:
            max_traces_per_query = int(max_traces_str)
        except (ValueError, TypeError) as e:
            logger.warning(
                f"Invalid MAX_TRACES_PER_QUERY value '{max_traces_str}': {e}. Using default: 500"
            )
            max_traces_per_query = 500

        return cls(
            backend=BackendConfig.from_env(),
            log_level=log_level,
            max_traces_per_query=max_traces_per_query,
        )

    def apply_cli_overrides(
        self,
        backend_type: str | None = None,
        backend_url: str | None = None,
        api_key: str | None = None,
        environments: str | None = None,
    ) -> None:
        """Apply CLI argument overrides to configuration."""
        if backend_type:
            if backend_type not in ["jaeger", "tempo", "traceloop"]:
                raise ValueError(
                    f"Invalid backend type: {backend_type}. "
                    "Must be one of: jaeger, tempo, traceloop"
                )
            self.backend.type = backend_type  # type: ignore

        if backend_url:
            self.backend.url = TypeAdapter(HttpUrl).validate_python(backend_url)

        if api_key:
            self.backend.api_key = api_key

        if environments:
            self.backend.environments = [
                env.strip() for env in environments.split(",") if env.strip()
            ]
