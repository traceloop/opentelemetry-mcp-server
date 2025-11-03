"""OpenLLMetry MCP Server - Main entry point."""

import asyncio
import logging
import sys

import click
from fastmcp import FastMCP

from openllmetry_mcp.backends.base import BaseBackend
from openllmetry_mcp.backends.jaeger import JaegerBackend
from openllmetry_mcp.backends.tempo import TempoBackend
from openllmetry_mcp.backends.traceloop import TraceloopBackend
from openllmetry_mcp.config import ServerConfig
from openllmetry_mcp.tools import errors, search, services, trace, usage

# Set up logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Global backend instance
_backend: BaseBackend | None = None
_config: ServerConfig | None = None

# Initialize FastMCP server
mcp = FastMCP("openllmetry-mcp")


def _create_backend(config: ServerConfig) -> BaseBackend:
    """Create backend instance based on configuration.

    Args:
        config: Server configuration

    Returns:
        Backend instance

    Raises:
        ValueError: If backend type is unsupported
    """
    backend_config = config.backend

    if backend_config.type == "jaeger":
        logger.info(f"Initializing Jaeger backend: {backend_config.url}")
        return JaegerBackend(
            url=str(backend_config.url),
            api_key=backend_config.api_key,
            timeout=backend_config.timeout,
        )
    elif backend_config.type == "tempo":
        logger.info(f"Initializing Tempo backend: {backend_config.url}")
        return TempoBackend(
            url=str(backend_config.url),
            api_key=backend_config.api_key,
            timeout=backend_config.timeout,
        )
    elif backend_config.type == "traceloop":
        logger.info(f"Initializing Traceloop backend: {backend_config.url}")
        return TraceloopBackend(
            url=str(backend_config.url),
            api_key=backend_config.api_key,
            timeout=backend_config.timeout,
        )
    else:
        raise ValueError(f"Unsupported backend type: {backend_config.type}")


async def _initialize_backend() -> None:
    """Initialize the backend and perform health check."""
    global _backend, _config

    if not _config:
        raise RuntimeError("Server configuration not set")

    # Create backend
    _backend = _create_backend(_config)

    # Health check
    try:
        health = await _backend.health_check()
        logger.info(f"Backend health check: {health}")
        if health.status != "healthy":
            logger.warning("Backend is not healthy, but continuing...")
    except Exception as e:
        logger.error(f"Backend health check failed: {e}")
        logger.warning("Continuing anyway, requests may fail...")


@mcp.tool()
async def search_traces(
    service_name: str | None = None,
    operation_name: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    min_duration_ms: int | None = None,
    max_duration_ms: int | None = None,
    gen_ai_system: str | None = None,
    gen_ai_model: str | None = None,
    has_error: bool | None = None,
    tags: dict[str, str] | None = None,
    limit: int = 100,
) -> str:
    """Search for OpenTelemetry traces with filters.

    Supports filtering by service, operation, time range, duration, LLM provider/model, and error status.

    Args:
        service_name: Filter by service name
        operation_name: Filter by operation/span name
        start_time: Start time in ISO 8601 format (e.g., 2024-01-01T00:00:00Z)
        end_time: End time in ISO 8601 format
        min_duration_ms: Minimum trace duration in milliseconds
        max_duration_ms: Maximum trace duration in milliseconds
        gen_ai_system: Filter by LLM provider (e.g., openai, anthropic)
        gen_ai_model: Filter by LLM model name (e.g., gpt-4, claude-3-opus)
        has_error: Filter traces with errors
        tags: Additional tag filters as key-value pairs
        limit: Maximum number of traces to return (1-1000, default: 100)

    Returns:
        JSON string with search results
    """
    if not _backend:
        return '{"error": "Backend not initialized"}'

    try:
        result = await search.search_traces(
            _backend,
            service_name=service_name,
            operation_name=operation_name,
            start_time=start_time,
            end_time=end_time,
            min_duration_ms=min_duration_ms,
            max_duration_ms=max_duration_ms,
            gen_ai_system=gen_ai_system,
            gen_ai_model=gen_ai_model,
            has_error=has_error,
            tags=tags,
            limit=limit,
        )
        return result
    except Exception as e:
        logger.error(f"Error executing search_traces: {e}", exc_info=True)
        return f'{{"error": "Tool execution failed: {str(e)}"}}'


@mcp.tool()
async def get_trace(trace_id: str) -> str:
    """Get complete trace details by trace ID.

    Returns all spans with attributes, including parsed OpenLLMetry data for LLM operations.

    Args:
        trace_id: Trace identifier

    Returns:
        JSON string with trace details
    """
    if not _backend:
        return '{"error": "Backend not initialized"}'

    try:
        result = await trace.get_trace(_backend, trace_id=trace_id)
        return result
    except Exception as e:
        logger.error(f"Error executing get_trace: {e}", exc_info=True)
        return f'{{"error": "Tool execution failed: {str(e)}"}}'


@mcp.tool()
async def get_llm_usage(
    start_time: str | None = None,
    end_time: str | None = None,
    service_name: str | None = None,
    gen_ai_system: str | None = None,
    gen_ai_model: str | None = None,
    limit: int = 1000,
) -> str:
    """Get aggregated LLM usage metrics (token counts) for a time period.

    Provides breakdowns by model and service.

    Args:
        start_time: Start time in ISO 8601 format
        end_time: End time in ISO 8601 format
        service_name: Filter by service name
        gen_ai_system: Filter by LLM provider
        gen_ai_model: Filter by LLM model name
        limit: Maximum traces to analyze (default: 1000)

    Returns:
        JSON string with usage metrics
    """
    if not _backend:
        return '{"error": "Backend not initialized"}'

    try:
        result = await usage.get_llm_usage(
            _backend,
            start_time=start_time,
            end_time=end_time,
            service_name=service_name,
            gen_ai_system=gen_ai_system,
            gen_ai_model=gen_ai_model,
            limit=limit,
        )
        return result
    except Exception as e:
        logger.error(f"Error executing get_llm_usage: {e}", exc_info=True)
        return f'{{"error": "Tool execution failed: {str(e)}"}}'


@mcp.tool()
async def list_services() -> str:
    """List all available services in the OpenTelemetry backend.

    Returns:
        JSON string with list of services
    """
    if not _backend:
        return '{"error": "Backend not initialized"}'

    try:
        result = await services.list_services(_backend)
        return result
    except Exception as e:
        logger.error(f"Error executing list_services: {e}", exc_info=True)
        return f'{{"error": "Tool execution failed: {str(e)}"}}'


@mcp.tool()
async def find_errors(
    start_time: str | None = None,
    end_time: str | None = None,
    service_name: str | None = None,
    limit: int = 100,
) -> str:
    """Find traces with errors.

    Including detailed error messages, stack traces, and LLM-specific error information.

    Args:
        start_time: Start time in ISO 8601 format
        end_time: End time in ISO 8601 format
        service_name: Filter by service name
        limit: Maximum error traces to return (default: 100)

    Returns:
        JSON string with error traces
    """
    if not _backend:
        return '{"error": "Backend not initialized"}'

    try:
        result = await errors.find_errors(
            _backend,
            start_time=start_time,
            end_time=end_time,
            service_name=service_name,
            limit=limit,
        )
        return result
    except Exception as e:
        logger.error(f"Error executing find_errors: {e}", exc_info=True)
        return f'{{"error": "Tool execution failed: {str(e)}"}}'


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
    transport: str,
    host: str,
    port: int,
) -> None:
    """OpenLLMetry MCP Server - Query OpenTelemetry traces from LLM applications.

    Supports multiple backends: Jaeger, Tempo, and Traceloop.
    Configuration can be provided via environment variables or CLI arguments.

    Transport options:
      - stdio (default): Standard input/output for local use (Claude Desktop)
      - http: HTTP server for network access (remote clients)

    Examples:
      # Run with stdio transport (default, for Claude Desktop)
      openllmetry-mcp --backend traceloop

      # Run with HTTP transport for network access
      openllmetry-mcp --transport http --port 8000

      # Run with HTTP on specific host/port
      openllmetry-mcp --transport http --host 127.0.0.1 --port 9000
    """
    global _config

    try:
        # Load configuration from environment
        _config = ServerConfig.from_env()

        # Set logging level
        logging.getLogger().setLevel(_config.log_level)

        # Apply CLI overrides
        if backend or url or api_key:
            _config.apply_cli_overrides(
                backend_type=backend,
                backend_url=url,
                api_key=api_key,
            )

        # Initialize backend before starting server
        asyncio.run(_initialize_backend())

        # Run server with selected transport
        if transport == "http":
            logger.info(f"Starting MCP server with HTTP transport on {host}:{port}")
            mcp.run(transport="sse", host=host, port=port)
        else:
            logger.info("Starting MCP server with stdio transport")
            mcp.run(transport="stdio")

    except KeyboardInterrupt:
        logger.info("Server stopped by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Server error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
