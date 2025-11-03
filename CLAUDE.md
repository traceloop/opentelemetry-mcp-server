# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Opentelemetry MCP Server (`opentelemetry-mcp`) is an MCP (Model Context Protocol) server that enables AI agents to query and analyze OpenTelemetry traces from LLM applications. It parses Opentelemetry semantic conventions (the `gen_ai.*` attributes) to enable automated debugging and observability.

**Key Features:**
- Multi-backend support: Jaeger, Grafana Tempo, and Traceloop
- 5 MCP tools: `search_traces`, `get_trace`, `get_llm_usage`, `list_services`, `find_errors`
- Token usage tracking and aggregation across models/services
- Dual transport modes: stdio (Claude Desktop) and HTTP/SSE (network access)

## Development Commands

**Package Manager:** This project uses UV (not pip). All commands should use `uv run`.

```bash
# Install dependencies
uv sync

# Run the server (stdio transport for Claude Desktop)
uv run opentelemetry-mcp

# Run with HTTP transport
uv run opentelemetry-mcp --transport http --port 8000

# Override backend configuration
uv run opentelemetry-mcp --backend jaeger --url http://localhost:16686

# Run all tests
uv run pytest

# Run with coverage
uv run pytest --cov=opentelemetry_mcp --cov-report=html

# Run specific test file
uv run pytest tests/test_models.py

# Format code (always run before committing)
uv run ruff format .

# Lint code
uv run ruff check .

# Type check (strict mode, must pass)
uv run mypy src/
```

## Architecture

### Backend Abstraction Pattern

All trace storage backends implement the `BaseBackend` abstract interface in [opentelemetry_mcp/backends/base.py](opentelemetry_mcp/backends/base.py):

```python
class BaseBackend(ABC):
    @abstractmethod
    async def search_traces(self, query: TraceQuery) -> list[TraceSummary]: ...
    @abstractmethod
    async def get_trace(self, trace_id: str) -> TraceData: ...
    @abstractmethod
    async def list_services(self) -> list[str]: ...
    @abstractmethod
    async def get_service_operations(self, service: str) -> list[str]: ...
    @abstractmethod
    async def health_check(self) -> bool: ...
```

Concrete implementations:
- [backends/jaeger.py](opentelemetry_mcp/backends/jaeger.py) - Jaeger backend
- [backends/tempo.py](opentelemetry_mcp/backends/tempo.py) - Grafana Tempo backend
- [backends/traceloop.py](opentelemetry_mcp/backends/traceloop.py) - Traceloop backend

### Tool-Based Architecture

Each MCP capability is implemented as a separate tool module in [opentelemetry_mcp/tools/](opentelemetry_mcp/tools/):
- [tools/search.py](opentelemetry_mcp/tools/search.py) - Search traces with filters
- [tools/trace.py](opentelemetry_mcp/tools/trace.py) - Get detailed trace by ID
- [tools/usage.py](opentelemetry_mcp/tools/usage.py) - Aggregate token usage metrics
- [tools/services.py](opentelemetry_mcp/tools/services.py) - List available services
- [tools/errors.py](opentelemetry_mcp/tools/errors.py) - Find traces with errors

**Critical:** All tools MUST return JSON strings (not dicts). This is required by the MCP protocol.

```python
# Correct
return json.dumps({"result": data})

# Incorrect - will break MCP protocol
return {"result": data}
```

### Key Components

- [server.py](opentelemetry_mcp/server.py) - FastMCP application, CLI interface, tool handlers
- [config.py](opentelemetry_mcp/config.py) - Pydantic configuration models
- [models.py](opentelemetry_mcp/models.py) - Core data models (SpanData, TraceData, UsageMetrics)
- [attributes.py](opentelemetry_mcp/attributes.py) - Strongly-typed OpenTelemetry attribute models

## Configuration

**Environment Variables** (see [.env.example](.env.example)):
- `BACKEND_TYPE` - Required: `jaeger`, `tempo`, or `traceloop`
- `BACKEND_URL` - Required: Backend API endpoint
- `BACKEND_API_KEY` - Optional: Authentication key
- `BACKEND_TIMEOUT` - Optional: Request timeout (default: 30s)
- `LOG_LEVEL` - Optional: Logging level (default: INFO)
- `MAX_TRACES_PER_QUERY` - Optional: Result limit (default: 100)

**Configuration Precedence:** CLI args > environment variables > defaults

## Opentelemetry Semantic Conventions

The server parses both current and legacy Opentelemetry conventions:

**Primary (gen_ai.*):**
- `gen_ai.system` - LLM provider (e.g., "openai", "anthropic")
- `gen_ai.request.model` - Model name (e.g., "gpt-4", "claude-3-opus")
- `gen_ai.usage.prompt_tokens` / `gen_ai.usage.input_tokens` - Input tokens
- `gen_ai.usage.completion_tokens` / `gen_ai.usage.output_tokens` - Output tokens
- `gen_ai.response.finish_reasons` - Completion reasons

**Legacy (llm.*):** Supported for backward compatibility
- `llm.system`, `llm.request.model`, etc.

**Token Naming Variations:**
- OpenAI: `prompt_tokens`, `completion_tokens`
- Anthropic: `input_tokens`, `output_tokens`

Parse attributes using: `LLMSpanAttributes.from_span(span_data)`

## Key Development Patterns

### 1. Type Safety
- Full type annotations required (MyPy strict mode)
- Use Pydantic models for all data structures
- Type checking must pass before committing

### 2. Async-First
- All backend operations are async
- Use `async with` for backend context managers
- Always `await` backend method calls

### 3. Pydantic Models
- Use for data validation and serialization
- Serialize with `model_dump(mode="json")` for JSON output
- Models automatically handle validation and type conversion

### 4. Error Handling
- Tools should catch exceptions and return JSON with `error` field
- Backend health checks are non-blocking
- Server starts even if backend is initially unhealthy

### 5. Adding New Backends
1. Create new file in [opentelemetry_mcp/backends/](opentelemetry_mcp/backends/)
2. Extend `BaseBackend` class
3. Implement all abstract methods
4. Add to backend factory in [config.py](opentelemetry_mcp/config.py)

### 6. Adding New Tools
1. Create new module in [opentelemetry_mcp/tools/](opentelemetry_mcp/tools/)
2. Implement tool function that takes backend and returns JSON string
3. Register in [server.py](opentelemetry_mcp/server.py) using `@mcp.tool()`

## Testing

- Use pytest with async support (pytest-asyncio)
- Fixtures defined in [tests/conftest.py](tests/conftest.py)
- Mock backend responses for tool tests
- All tests must pass before merging

## Python Version

- Minimum: Python 3.11
- CI uses: Python 3.12
- Version file: [.python-version](.python-version)
