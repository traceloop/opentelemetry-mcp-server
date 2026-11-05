"""Opentelemetry MCP Server - Main entry point."""

import json
import logging
import sys
from typing import Any

import click
from fastmcp import FastMCP
from pydantic import BaseModel

from opentelemetry_mcp.backends.base import BaseBackend
from opentelemetry_mcp.backends.jaeger import JaegerBackend
from opentelemetry_mcp.backends.tempo import TempoBackend
from opentelemetry_mcp.backends.traceloop import TraceloopBackend
from opentelemetry_mcp.config import ServerConfig
from opentelemetry_mcp.tools import (
    errors,
    expensive_traces,
    list_llm_tools,
    list_models,
    model_stats,
    search,
    search_spans,
    services,
    slow_traces,
    trace,
    usage,
)

# Set up logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def _handle_tool_error(tool_name: str, error: Exception) -> str:
    """Centralized error handler for tool functions.

    Logs the error with traceback and returns properly escaped JSON.

    Args:
        tool_name: Name of the tool that encountered the error
        error: The exception that was raised

    Returns:
        JSON string with error message
    """
    logger.error(f"Error executing {tool_name}: {error}", exc_info=True)
    return json.dumps({"error": f"Tool execution failed: {str(error)}"})


class EnvironmentsResponse(BaseModel):
    """Response model for the list_environments tool."""

    environments: list[str]
    default_environment: str


# Global backend instances per environment
_backends: dict[str, BaseBackend] = {}
_default_environment: str = "default"
_health_checked: set[str] = set()
_config: ServerConfig | None = None

# Initialize FastMCP server
mcp = FastMCP("opentelemetry-mcp")


def _create_backends(config: ServerConfig) -> dict[str, BaseBackend]:
    """Instantiate one backend per configured environment URL.

    Args:
        config: Server configuration

    Returns:
        Mapping of environment name to backend instance

    Raises:
        ValueError: If backend type is unsupported
    """
    backend_config = config.backend

    # Backward compatibility: if no named URLs are configured, fall back to the
    # single legacy `url` field keyed under the default environment.
    if backend_config.backend_urls:
        urls = backend_config.backend_urls
    else:
        urls = {backend_config.default_environment: backend_config.url}

    backends: dict[str, BaseBackend] = {}
    for name, url in urls.items():
        url_str = str(url)
        if backend_config.type == "jaeger":
            logger.info(f"Initializing Jaeger backend '{name}': {url_str}")
            backends[name] = JaegerBackend(
                url=url_str,
                api_key=backend_config.api_key,
                timeout=backend_config.timeout,
            )
        elif backend_config.type == "tempo":
            logger.info(f"Initializing Tempo backend '{name}': {url_str}")
            backends[name] = TempoBackend(
                url=url_str,
                api_key=backend_config.api_key,
                timeout=backend_config.timeout,
            )
        elif backend_config.type == "traceloop":
            logger.info(f"Initializing Traceloop backend '{name}': {url_str}")
            backends[name] = TraceloopBackend(
                url=url_str,
                api_key=backend_config.api_key,
                timeout=backend_config.timeout,
                environments=backend_config.environments,
            )
        else:
            raise ValueError(f"Unsupported backend type: {backend_config.type}")

    return backends


async def _get_backend(environment: str | None = None) -> BaseBackend:
    """Get (lazily creating) the backend for the given environment.

    This ensures backends are always created within FastMCP's event loop,
    avoiding "Event loop is closed" errors from premature initialization.

    Args:
        environment: Target environment name (e.g., 'prod', 'qa', 'dev').
            Uses the default environment when omitted.

    Returns:
        Backend instance for the requested environment

    Raises:
        RuntimeError: If server configuration is not set
        ValueError: If the environment is unknown
    """
    global _backends, _default_environment, _config

    if not _config:
        raise RuntimeError("Server configuration not set")

    # Lazily create backends on first use
    if not _backends:
        logger.info("Creating backends in current event loop")
        _backends = _create_backends(_config)
        _default_environment = _config.backend.default_environment

    env = environment or _default_environment
    if env not in _backends:
        raise ValueError(f"Unknown environment '{env}'. Available: {sorted(_backends)}")

    backend = _backends[env]

    # Health-check the selected environment once, on first use, so an
    # unreachable backend in another environment does not delay this request.
    if env not in _health_checked:
        _health_checked.add(env)
        try:
            health = await backend.health_check()
            logger.info(f"Backend '{env}' health check: {health}")
            if health.status != "healthy":
                logger.warning(f"Backend '{env}' is not healthy, but continuing...")
        except Exception as e:
            logger.error(f"Backend '{env}' health check failed: {e}")
            logger.warning("Continuing anyway, requests may fail...")

    return backend


@mcp.tool()
async def search_traces(
    service_name: str | None = None,
    operation_name: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    min_duration_ms: int | None = None,
    max_duration_ms: int | None = None,
    gen_ai_system: str | None = None,
    gen_ai_request_model: str | None = None,
    gen_ai_response_model: str | None = None,
    has_error: bool | None = None,
    tags: dict[str, str] | None = None,
    filters: list[dict[str, Any]] | None = None,
    limit: int = 100,
    environment: str | None = None,
) -> str:
    """Search for OpenTelemetry traces with filters.

    Supports both simple parameters and advanced generic filter system.

    Args:
        service_name: Filter by service name (use filters for advanced queries)
        operation_name: Filter by operation/span name
        start_time: Start time in ISO 8601 format (e.g., 2024-01-01T00:00:00Z)
        end_time: End time in ISO 8601 format
        min_duration_ms: Minimum trace duration in milliseconds
        max_duration_ms: Maximum trace duration in milliseconds
        gen_ai_system: Filter by LLM provider (e.g., openai, anthropic)
        gen_ai_request_model: Filter by requested model name (e.g., gpt-4)
        gen_ai_response_model: Filter by actual model used (e.g., gpt-4-0613)
        has_error: Filter traces with errors
        tags: Additional tag filters as key-value pairs
        filters: Generic filter conditions (advanced) - list of filter objects with:
            - field: Field name in dotted notation (e.g., "gen_ai.usage.prompt_tokens")
            - operator: Comparison operator (equals, not_equals, gt, lt, gte, lte, contains,
                       not_contains, starts_with, ends_with, in, not_in, between, exists, not_exists)
            - value: Single value for most operators
            - values: List of values for "in", "not_in", "between" operators
            - value_type: Type of value(s) - "string", "number", or "boolean"
        limit: Maximum number of traces to return (1-1000, default: 100)
        environment: Target environment name (e.g., 'prod', 'qa', 'dev'). Uses default if omitted.

    Returns:
        JSON string with search results

    Filter Examples:
        Find expensive traces:
        {"field": "gen_ai.usage.total_tokens", "operator": "gt", "value": 5000, "value_type": "number"}

        Filter by multiple models:
        {"field": "gen_ai.request.model", "operator": "in", "values": ["gpt-4", "claude-3"], "value_type": "string"}

        Check if attribute exists:
        {"field": "gen_ai.request.temperature", "operator": "exists", "value_type": "number"}

        Find streaming requests:
        {"field": "gen_ai.request.is_streaming", "operator": "equals", "value": true, "value_type": "boolean"}
    """
    try:
        backend = await _get_backend(environment)
        result = await search.search_traces(
            backend,
            service_name=service_name,
            operation_name=operation_name,
            start_time=start_time,
            end_time=end_time,
            min_duration_ms=min_duration_ms,
            max_duration_ms=max_duration_ms,
            gen_ai_system=gen_ai_system,
            gen_ai_request_model=gen_ai_request_model,
            gen_ai_response_model=gen_ai_response_model,
            has_error=has_error,
            tags=tags,
            filters=filters,
            limit=limit,
        )
        return result
    except Exception as e:
        return _handle_tool_error("search_traces", e)


@mcp.tool()
async def get_trace(trace_id: str, environment: str | None = None) -> str:
    """Get complete trace details by trace ID.

    Returns all spans with attributes, including parsed Opentelemetry data for LLM operations.

    Args:
        trace_id: Trace identifier
        environment: Target environment name (e.g., 'prod', 'qa', 'dev'). Uses default if omitted.

    Returns:
        JSON string with trace details
    """
    try:
        backend = await _get_backend(environment)
        result = await trace.get_trace(backend, trace_id=trace_id)
        return result
    except Exception as e:
        return _handle_tool_error("get_trace", e)


@mcp.tool()
async def get_llm_usage(
    start_time: str | None = None,
    end_time: str | None = None,
    service_name: str | None = None,
    gen_ai_system: str | None = None,
    gen_ai_request_model: str | None = None,
    gen_ai_response_model: str | None = None,
    limit: int = 1000,
    environment: str | None = None,
) -> str:
    """Get aggregated LLM usage metrics (token counts) for a time period.

    Provides breakdowns by model and service.

    Args:
        start_time: Start time in ISO 8601 format
        end_time: End time in ISO 8601 format
        service_name: Filter by service name
        gen_ai_system: Filter by LLM provider
        gen_ai_request_model: Filter by requested model name
        gen_ai_response_model: Filter by actual model used
        limit: Maximum traces to analyze (default: 1000)
        environment: Target environment name (e.g., 'prod', 'qa', 'dev'). Uses default if omitted.

    Returns:
        JSON string with usage metrics
    """
    try:
        backend = await _get_backend(environment)
        result = await usage.get_llm_usage(
            backend,
            start_time=start_time,
            end_time=end_time,
            service_name=service_name,
            gen_ai_system=gen_ai_system,
            gen_ai_request_model=gen_ai_request_model,
            gen_ai_response_model=gen_ai_response_model,
            limit=limit,
        )
        return result
    except Exception as e:
        return _handle_tool_error("get_llm_usage", e)


@mcp.tool()
async def list_services(environment: str | None = None) -> str:
    """List all available services in the OpenTelemetry backend.

    Args:
        environment: Target environment name (e.g., 'prod', 'qa', 'dev'). Uses default if omitted.

    Returns:
        JSON string with list of services
    """
    try:
        backend = await _get_backend(environment)
        result = await services.list_services(backend)
        return result
    except Exception as e:
        return _handle_tool_error("list_services", e)


@mcp.tool()
async def find_errors(
    start_time: str | None = None,
    end_time: str | None = None,
    service_name: str | None = None,
    limit: int = 100,
    environment: str | None = None,
) -> str:
    """Find traces with errors.

    Including detailed error messages, stack traces, and LLM-specific error information.

    Args:
        start_time: Start time in ISO 8601 format
        end_time: End time in ISO 8601 format
        service_name: Filter by service name
        limit: Maximum error traces to return (default: 100)
        environment: Target environment name (e.g., 'prod', 'qa', 'dev'). Uses default if omitted.

    Returns:
        JSON string with error traces
    """
    try:
        backend = await _get_backend(environment)
        result = await errors.find_errors(
            backend,
            start_time=start_time,
            end_time=end_time,
            service_name=service_name,
            limit=limit,
        )
        return result
    except Exception as e:
        return _handle_tool_error("find_errors", e)


@mcp.tool()
async def list_llm_models(
    start_time: str | None = None,
    end_time: str | None = None,
    service_name: str | None = None,
    gen_ai_system: str | None = None,
    limit: int = 1000,
    environment: str | None = None,
) -> str:
    """List all LLM models being used with usage statistics.

    Discovers what models are deployed and tracks their usage patterns.

    Args:
        start_time: Start time in ISO 8601 format (e.g., 2024-01-01T00:00:00Z)
        end_time: End time in ISO 8601 format
        service_name: Filter by service name
        gen_ai_system: Filter by LLM provider (e.g., openai, anthropic, cohere)
        limit: Maximum traces to analyze for model discovery (default: 1000)
        environment: Target environment name (e.g., 'prod', 'qa', 'dev'). Uses default if omitted.

    Returns:
        JSON string with list of models and their statistics (count, request_count, first_seen, last_seen)
    """
    try:
        backend = await _get_backend(environment)
        result = await list_models.list_models(
            backend,
            start_time=start_time,
            end_time=end_time,
            service_name=service_name,
            gen_ai_system=gen_ai_system,
            limit=limit,
        )
        return result
    except Exception as e:
        return _handle_tool_error("list_llm_models", e)


@mcp.tool()
async def get_llm_model_stats(
    model_name: str,
    start_time: str | None = None,
    end_time: str | None = None,
    service_name: str | None = None,
    environment: str | None = None,
) -> str:
    """Get detailed performance statistics for a specific LLM model.

    Analyzes request count, latency percentiles (p50, p95, p99), token usage statistics,
    error rates, and finish reason distributions.

    Args:
        model_name: Model name to analyze (e.g., "gpt-4", "claude-3-opus", "gpt-3.5-turbo")
        start_time: Start time in ISO 8601 format (e.g., 2024-01-01T00:00:00Z)
        end_time: End time in ISO 8601 format
        service_name: Filter by service name
        environment: Target environment name (e.g., 'prod', 'qa', 'dev'). Uses default if omitted.

    Returns:
        JSON string with comprehensive model statistics including duration/token percentiles
    """
    try:
        backend = await _get_backend(environment)
        result = await model_stats.get_model_stats(
            backend,
            model_name=model_name,
            start_time=start_time,
            end_time=end_time,
            service_name=service_name,
        )
        return result
    except Exception as e:
        return _handle_tool_error("get_llm_model_stats", e)


@mcp.tool()
async def get_llm_expensive_traces(
    limit: int = 10,
    start_time: str | None = None,
    end_time: str | None = None,
    min_tokens: int | None = None,
    service_name: str | None = None,
    gen_ai_request_model: str | None = None,
    gen_ai_response_model: str | None = None,
    environment: str | None = None,
) -> str:
    """Find traces with highest LLM token usage.

    Useful for cost optimization and identifying inefficient prompts.

    Args:
        limit: Maximum number of traces to return (default: 10)
        start_time: Start time in ISO 8601 format (e.g., 2024-01-01T00:00:00Z)
        end_time: End time in ISO 8601 format
        min_tokens: Minimum token count threshold (only return traces above this)
        service_name: Filter by service name
        gen_ai_request_model: Filter by requested model name (e.g., "gpt-4")
        gen_ai_response_model: Filter by actual model used (e.g., "gpt-4-0613")
        environment: Target environment name (e.g., 'prod', 'qa', 'dev'). Uses default if omitted.

    Returns:
        JSON string with top N most expensive traces sorted by total token usage
    """
    try:
        backend = await _get_backend(environment)
        result = await expensive_traces.get_expensive_traces(
            backend,
            limit=limit,
            start_time=start_time,
            end_time=end_time,
            min_tokens=min_tokens,
            service_name=service_name,
            gen_ai_request_model=gen_ai_request_model,
            gen_ai_response_model=gen_ai_response_model,
        )
        return result
    except Exception as e:
        return _handle_tool_error("get_llm_expensive_traces", e)


@mcp.tool()
async def get_llm_slow_traces(
    limit: int = 10,
    start_time: str | None = None,
    end_time: str | None = None,
    min_duration_ms: int | None = None,
    service_name: str | None = None,
    gen_ai_request_model: str | None = None,
    gen_ai_response_model: str | None = None,
    environment: str | None = None,
) -> str:
    """Find slowest LLM traces by duration.

    Useful for performance optimization and identifying latency bottlenecks.

    Args:
        limit: Maximum number of traces to return (default: 10)
        start_time: Start time in ISO 8601 format (e.g., 2024-01-01T00:00:00Z)
        end_time: End time in ISO 8601 format
        min_duration_ms: Minimum duration threshold in milliseconds (only return traces above this)
        service_name: Filter by service name
        gen_ai_request_model: Filter by requested model name (e.g., "gpt-4")
        gen_ai_response_model: Filter by actual model used (e.g., "gpt-4-0613")
        environment: Target environment name (e.g., 'prod', 'qa', 'dev'). Uses default if omitted.

    Returns:
        JSON string with top N slowest traces sorted by duration
    """
    try:
        backend = await _get_backend(environment)
        result = await slow_traces.get_slow_traces(
            backend,
            limit=limit,
            start_time=start_time,
            end_time=end_time,
            min_duration_ms=min_duration_ms,
            service_name=service_name,
            gen_ai_request_model=gen_ai_request_model,
            gen_ai_response_model=gen_ai_response_model,
        )
        return result
    except Exception as e:
        return _handle_tool_error("get_llm_slow_traces", e)


@mcp.tool()
async def search_spans_tool(
    service_name: str | None = None,
    operation_name: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    min_duration_ms: int | None = None,
    max_duration_ms: int | None = None,
    gen_ai_system: str | None = None,
    gen_ai_request_model: str | None = None,
    gen_ai_response_model: str | None = None,
    has_error: bool | None = None,
    tags: dict[str, str] | None = None,
    filters: list[dict[str, Any]] | None = None,
    limit: int = 100,
    environment: str | None = None,
) -> str:
    """Search for individual OpenTelemetry spans with optional filters.

    Unlike search_traces, this returns individual spans rather than grouped traces,
    which is useful for analyzing specific operations or finding spans with certain
    characteristics (e.g., LLM tool calls with traceloop.span.kind == tool).

    Args:
        service_name: Filter by service name
        operation_name: Filter by operation/span name
        start_time: Start time in ISO 8601 format (e.g., 2024-01-01T00:00:00Z)
        end_time: End time in ISO 8601 format
        min_duration_ms: Minimum span duration in milliseconds
        max_duration_ms: Maximum span duration in milliseconds
        gen_ai_system: Filter by LLM provider (e.g., openai, anthropic)
        gen_ai_request_model: Filter by requested model name (e.g., "gpt-4")
        gen_ai_response_model: Filter by actual model used (e.g., "gpt-4-0613")
        has_error: Filter spans with errors
        tags: Additional tag filters as key-value pairs
        filters: Generic filter conditions - list of filter objects with:
            - field: Field name in dotted notation (e.g., "traceloop.span.kind")
            - operator: Comparison operator
            - value: Single value for most operators
            - values: List of values for "in", "not_in", "between" operators
            - value_type: Type of value(s) - "string", "number", or "boolean"
        limit: Maximum number of spans to return (1-1000, default: 100)
        environment: Target environment name (e.g., 'prod', 'qa', 'dev'). Uses default if omitted.

    Returns:
        JSON string with span summaries

    Example filter to find LLM tool calls:
        {"field": "traceloop.span.kind", "operator": "equals", "value": "tool", "value_type": "string"}
    """
    try:
        backend = await _get_backend(environment)
        result = await search_spans.search_spans(
            backend,
            service_name=service_name,
            operation_name=operation_name,
            start_time=start_time,
            end_time=end_time,
            min_duration_ms=min_duration_ms,
            max_duration_ms=max_duration_ms,
            gen_ai_system=gen_ai_system,
            gen_ai_request_model=gen_ai_request_model,
            gen_ai_response_model=gen_ai_response_model,
            has_error=has_error,
            tags=tags,
            filters=filters,
            limit=limit,
        )
        return result
    except Exception as e:
        return _handle_tool_error("search_spans_tool", e)


@mcp.tool()
async def list_llm_tools_tool(
    start_time: str | None = None,
    end_time: str | None = None,
    service_name: str | None = None,
    gen_ai_system: str | None = None,
    limit: int = 1000,
    environment: str | None = None,
) -> str:
    """List all LLM tools being used by identifying traceloop.span.kind == tool.

    Discovers which tools/functions LLM applications are calling, grouped by tool name
    with usage statistics.

    Args:
        start_time: Start time in ISO 8601 format (e.g., 2024-01-01T00:00:00Z)
        end_time: End time in ISO 8601 format
        service_name: Filter by service name
        gen_ai_system: Filter by LLM provider (openai, anthropic, etc.)
        limit: Maximum spans to analyze (default: 1000)
        environment: Target environment name (e.g., 'prod', 'qa', 'dev'). Uses default if omitted.

    Returns:
        JSON string with list of tools and their statistics (usage count, services, first/last seen)
    """
    try:
        backend = await _get_backend(environment)
        result = await list_llm_tools.list_llm_tools(
            backend,
            start_time=start_time,
            end_time=end_time,
            service_name=service_name,
            gen_ai_system=gen_ai_system,
            limit=limit,
        )
        return result
    except Exception as e:
        return _handle_tool_error("list_llm_tools_tool", e)


@mcp.tool()
async def list_environments() -> str:
    """List all configured backend environments.

    Returns the available environment names and which one is used by default
    when no environment is specified in a tool call.

    Returns:
        JSON string with environments list and default environment name
    """
    try:
        # Ensure backends are initialised
        await _get_backend()
        response = EnvironmentsResponse(
            environments=sorted(_backends.keys()),
            default_environment=_default_environment,
        )
        return json.dumps(response.model_dump(mode="json"), indent=2)
    except Exception as e:
        return _handle_tool_error("list_environments", e)


@click.command()
@click.option(
    "--backend",
    type=click.Choice(["jaeger", "tempo", "traceloop"]),
    help="Backend type (overrides BACKEND_TYPE env var)",
)
@click.option(
    "--url",
    type=str,
    help="Backend URL (overrides BACKEND_URL env var)",
)
@click.option(
    "--api-key",
    type=str,
    help="API key for backend authentication (overrides BACKEND_API_KEY env var)",
)
@click.option(
    "--environments",
    type=str,
    help="Comma-separated list of environments for Traceloop backend (overrides BACKEND_ENVIRONMENTS env var)",
)
@click.option(
    "--backend-urls",
    type=str,
    help="Named backend URLs as JSON or comma-separated key=url pairs (e.g., 'prod=https://...,qa=https://...'). Overrides BACKEND_URLS env var.",
)
@click.option(
    "--default-environment",
    type=str,
    help="Default environment name when none is specified in a tool call. Overrides DEFAULT_ENVIRONMENT env var.",
)
@click.option(
    "--transport",
    type=click.Choice(["stdio", "http"]),
    default="stdio",
    help="Transport type: stdio (default) for local/Claude Desktop, http for network access",
)
@click.option(
    "--host",
    type=str,
    default="0.0.0.0",
    help="Host to bind HTTP server to (only for --transport http, default: 0.0.0.0)",
)
@click.option(
    "--port",
    type=int,
    default=8000,
    help="Port for HTTP server (only for --transport http, default: 8000)",
)
def main(
    backend: str | None,
    url: str | None,
    api_key: str | None,
    environments: str | None,
    backend_urls: str | None,
    default_environment: str | None,
    transport: str,
    host: str,
    port: int,
) -> None:
    """Opentelemetry MCP Server - Query OpenTelemetry traces from LLM applications.

    Supports multiple backends: Jaeger, Tempo, and Traceloop.
    Configuration can be provided via environment variables or CLI arguments.

    Transport options:
      - stdio (default): Standard input/output for local use (Claude Desktop)
      - http: HTTP server for network access (remote clients)

    Examples:
      # Run with stdio transport (default, for Claude Desktop)
      opentelemetry-mcp --backend traceloop

      # Run with HTTP transport for network access
      opentelemetry-mcp --transport http --port 8000

      # Run with HTTP on specific host/port
      opentelemetry-mcp --transport http --host 127.0.0.1 --port 9000
    """
    global _config

    try:
        # Load configuration from environment
        _config = ServerConfig.from_env()

        # Set logging level
        logging.getLogger().setLevel(_config.log_level)

        # Apply CLI overrides
        if backend or url or api_key or environments or backend_urls or default_environment:
            _config.apply_cli_overrides(
                backend_type=backend,
                backend_url=url,
                api_key=api_key,
                environments=environments,
                backend_urls=backend_urls,
                default_environment=default_environment,
            )

        # Backend will be lazily initialized on first tool call
        # This ensures it's created in FastMCP's event loop, not a separate one

        # Run server with selected transport
        if transport == "http":
            logger.info(f"Starting MCP server with HTTP transport on {host}:{port}")
            logger.info("Using streamable-http transport for better compatibility")
            logger.info(f"Connect clients to: http://{host}:{port}/mcp")
            mcp.run(transport="streamable-http", host=host, port=port)
        else:
            logger.info(
                f"Starting MCP server with stdio transport using Backend: {_config.backend.type} "
                f"connected to environments: "
                f"{sorted(_config.backend.backend_urls) or [_config.backend.default_environment]}"
            )
            mcp.run(transport="stdio")

    except KeyboardInterrupt:
        logger.info("Server stopped by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Server error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
