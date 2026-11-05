"""Configuration management for Opentelemetry MCP Server."""

import json
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
    backend_urls: dict[str, HttpUrl] = Field(default_factory=dict)
    default_environment: str = "default"

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: HttpUrl) -> HttpUrl:
        """Validate URL scheme."""
        if v.scheme not in ["http", "https"]:
            raise ValueError("URL must use http or https scheme")
        return v

    @classmethod
    def parse_backend_urls(cls, raw: str) -> dict[str, HttpUrl]:
        """Parse BACKEND_URLS value.

        Accepts two formats:
          JSON:     '{"prod": "https://...", "qa": "https://..."}'
          Comma-kv: 'prod=https://...,qa=https://...'

        In the comma-separated format only the first ``=`` is treated as the
        key/value separator, so URLs containing ``=`` in query strings survive.

        Args:
            raw: Raw BACKEND_URLS value

        Returns:
            Mapping of environment name to backend URL

        Raises:
            ValueError: If the value cannot be parsed
        """
        parsed: dict[str, str]
        try:
            decoded = json.loads(raw)
        except json.JSONDecodeError:
            if not raw.strip():
                raise ValueError("BACKEND_URLS must not be empty")
            parsed = {}
            for item in raw.split(","):
                if "=" not in item:
                    raise ValueError(
                        f"Invalid BACKEND_URLS entry '{item}'. Expected 'name=url' pairs."
                    )
                name, url = item.split("=", 1)
                name = name.strip()
                url = url.strip()
                if not name:
                    raise ValueError("BACKEND_URLS environment names must not be empty")
                parsed[name] = url
        else:
            if not isinstance(decoded, dict):
                raise ValueError(
                    "BACKEND_URLS JSON value must be an object mapping environment names to URLs"
                )
            parsed = {str(k): str(v) for k, v in decoded.items()}

        backend_urls: dict[str, HttpUrl] = {}
        for name, url in parsed.items():
            if not name.strip():
                raise ValueError("BACKEND_URLS environment names must not be empty")
            try:
                backend_urls[name] = TypeAdapter(HttpUrl).validate_python(url)
            except Exception as e:
                raise ValueError(
                    f"Invalid URL '{url}' for environment '{name}' in BACKEND_URLS: {e}"
                ) from e

        if not backend_urls:
            raise ValueError("BACKEND_URLS must contain at least one environment mapping")
        return backend_urls

    @classmethod
    def from_env(cls) -> "BackendConfig":
        """Load configuration from environment variables."""
        backend_type = os.getenv("BACKEND_TYPE", "jaeger")
        backend_url = os.getenv("BACKEND_URL")
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

        # Multi-environment routing configuration
        default_environment_raw = os.getenv("DEFAULT_ENVIRONMENT")
        default_environment = (default_environment_raw or "default").strip()
        if not default_environment:
            logger.warning("DEFAULT_ENVIRONMENT is empty. Using default: 'default'")
            default_environment = "default"

        backend_urls_raw = os.getenv("BACKEND_URLS")
        if backend_urls_raw:
            backend_urls = cls.parse_backend_urls(backend_urls_raw)
        elif backend_url:
            # Backward compatibility: a single legacy BACKEND_URL is treated as the
            # sole backend, keyed under the default environment.
            backend_urls = {default_environment: TypeAdapter(HttpUrl).validate_python(backend_url)}
        else:
            backend_urls = {
                default_environment: TypeAdapter(HttpUrl).validate_python("http://localhost:16686")
            }

        # The effective default environment must always resolve to a configured
        # backend; otherwise every default-routed tool call would fail at runtime.
        if default_environment not in backend_urls:
            if default_environment_raw:
                raise ValueError(
                    f"DEFAULT_ENVIRONMENT '{default_environment}' is not one of the configured "
                    f"environments in BACKEND_URLS: {sorted(backend_urls)}"
                )
            # No explicit DEFAULT_ENVIRONMENT: fall back to the first configured
            # environment so a bare BACKEND_URLS remains usable.
            default_environment = next(iter(backend_urls))
            logger.warning(
                f"DEFAULT_ENVIRONMENT is not set and 'default' is not one of the configured "
                f"environments: {sorted(backend_urls)}. Using '{default_environment}'."
            )

        # The legacy `url` field mirrors the default environment's URL so
        # consumers not yet aware of backend_urls keep working unchanged.
        url = backend_urls[default_environment]

        return cls(
            type=backend_type,  # type: ignore
            url=url,
            api_key=os.getenv("BACKEND_API_KEY"),
            timeout=timeout,
            environments=environments,
            backend_urls=backend_urls,
            default_environment=default_environment,
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
        backend_urls: str | None = None,
        default_environment: str | None = None,
    ) -> None:
        """Apply CLI argument overrides to configuration."""
        if backend_type:
            if backend_type not in ["jaeger", "tempo", "traceloop"]:
                raise ValueError(
                    f"Invalid backend type: {backend_type}. "
                    "Must be one of: jaeger, tempo, traceloop"
                )
            self.backend.type = backend_type  # type: ignore

        if api_key:
            self.backend.api_key = api_key

        if environments:
            self.backend.environments = [
                env.strip() for env in environments.split(",") if env.strip()
            ]

        if default_environment:
            self.backend.default_environment = default_environment

        if backend_url:
            validated_url = TypeAdapter(HttpUrl).validate_python(backend_url)
            self.backend.url = validated_url
            # Keep backend_urls in sync so the legacy --url flag remains
            # effective when BACKEND_URLS / --backend-urls are configured.
            self.backend.backend_urls[self.backend.default_environment] = validated_url

        if backend_urls:
            # Applied last so that --backend-urls stays authoritative over --url.
            self.backend.backend_urls = BackendConfig.parse_backend_urls(backend_urls)

        # Validate the final state: the effective default environment must
        # resolve to a configured backend after all overrides are applied.
        if (
            self.backend.backend_urls
            and self.backend.default_environment not in self.backend.backend_urls
        ):
            raise ValueError(
                f"Default environment '{self.backend.default_environment}' is not one of "
                f"the configured environments: {sorted(self.backend.backend_urls)}"
            )
