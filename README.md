# OpenTelemetry-MCP-Server
Unified MCP server for querying OpenTelemetry traces across multiple backends (Jaeger, Tempo, Traceloop, etc.), enabling AI agents to analyze distributed traces for automated debugging and observability.

An MCP (Model Context Protocol) server for querying OpenTelemetry traces from LLM applications, with specialized support for OpenLLMetry semantic conventions.

## Features

- **Multiple Backend Support**: Query traces from Jaeger, Grafana Tempo, or Traceloop
- **OpenLLMetry Integration**: Automatic parsing of `gen_ai.*` semantic conventions
- **5 Powerful Tools**:
  - `search_traces` - Search traces with advanced filters
  - `get_trace` - Get complete trace details
  - `get_llm_usage` - Aggregate token usage metrics
  - `list_services` - List available services
  - `find_errors` - Find traces with errors
- **Token Usage Tracking**: Aggregate prompt/completion tokens across models and services
- **CLI Overrides**: Configure via environment or command-line arguments
- **Type-Safe**: Built with Pydantic for robust data validation

## Installation

### Prerequisites

- Python 3.11 or higher
- [UV package manager](https://github.com/astral-sh/uv) (recommended) or pip

### Install with UV

```bash
# Clone the repository
cd openllmetry-mcp

# Install dependencies
uv sync

# Or install in development mode
uv pip install -e ".[dev]"
```

### Install with pip

```bash
pip install -e .
```

## Quick Start

The easiest way to run the server locally is using the provided startup script:

```bash
# 1. Configure your backend in start_locally.sh
# Edit the file and uncomment your preferred backend (Jaeger, Traceloop, or Tempo)

# 2. Run the script
./start_locally.sh
```

The script will:
- Auto-detect the project directory (works from anywhere)
- Verify `uv` is installed
- Set up your backend configuration
- Start the MCP server in stdio mode (ready for Claude Desktop)

**Supported Backends:**
- **Jaeger** (local): `http://localhost:16686`
- **Traceloop** (cloud): `https://api.traceloop.com` (requires API key)
- **Tempo** (local): `http://localhost:3200`

Edit [start_locally.sh](start_locally.sh) to switch between backends or adjust configuration.

## Configuration

### Environment Variables

Create a `.env` file (see `.env.example`):

```bash
# Backend type: jaeger, tempo, or traceloop
BACKEND_TYPE=jaeger

# Backend URL
BACKEND_URL=http://localhost:16686

# Optional: API key (mainly for Traceloop)
BACKEND_API_KEY=

# Optional: Request timeout (default: 30s)
BACKEND_TIMEOUT=30

# Optional: Logging level
LOG_LEVEL=INFO

# Optional: Max traces per query (default: 100)
MAX_TRACES_PER_QUERY=100
```

### Backend-Specific Configuration

#### Jaeger

```bash
BACKEND_TYPE=jaeger
BACKEND_URL=http://localhost:16686
```

#### Grafana Tempo

```bash
BACKEND_TYPE=tempo
BACKEND_URL=http://localhost:3200
```

#### Traceloop

```bash
BACKEND_TYPE=traceloop
BACKEND_URL=https://api.traceloop.com/v2
BACKEND_API_KEY=your_api_key_here
```

**Note**: The API key contains the project information. The backend uses a hardcoded project slug of `"default"` and Traceloop resolves the actual project and environment from the API key.

### CLI Overrides

You can override environment variables with CLI arguments:

```bash
openllmetry-mcp --backend jaeger --url http://localhost:16686
openllmetry-mcp --backend traceloop --url https://api.traceloop.com --api-key YOUR_KEY
```

## Usage

### Quick Start with start_locally.sh (Recommended)

The easiest way to run the server:

```bash
./start_locally.sh
```

This script handles all configuration and starts the server in stdio mode (perfect for Claude Desktop integration). To switch backends, simply edit the script and uncomment your preferred backend.

### Manual Running

For advanced use cases or custom configurations, you can run the server manually.

#### stdio Transport (for Claude Desktop)

Start the MCP server with stdio transport for local/Claude Desktop integration:

```bash
openllmetry-mcp
# or with UV
uv run openllmetry-mcp

# With backend override
uv run openllmetry-mcp --backend jaeger --url http://localhost:16686
```

#### HTTP Transport (for Network Access)

Start the MCP server with HTTP/SSE transport for remote access:

```bash
# Start HTTP server on default port 8000
openllmetry-mcp --transport http

# Or with UV
uv run openllmetry-mcp --transport http

# Specify custom host and port
uv run openllmetry-mcp --transport http --host 127.0.0.1 --port 9000
```

The HTTP server will be accessible at `http://localhost:8000/sse` by default.

**Transport Use Cases:**
- **stdio transport**: Local use, Claude Desktop integration, single process
- **HTTP transport**: Remote access, multiple clients, network deployment, sample applications

### Integrating with Claude Desktop

Configure the MCP server in your Claude Desktop config file:
- **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`

#### Why Two Configuration Approaches?

This server supports **3 different backends** (Jaeger, Tempo, Traceloop). We provide two integration methods to suit different use cases:

- **Wrapper Script** (`start_locally.sh`) → Easy backend switching for development/testing
- **Direct Configuration** → Standard MCP pattern, better for production or single-backend setups

Choose the approach that fits your workflow. See [Best Practices](#best-practices-choosing-an-approach) below for guidance.

#### Option 1: Using start_locally.sh (Recommended for Development)

**Best for:** Frequent backend switching, local development, testing multiple backends

```json
{
  "mcpServers": {
    "opentelemetry-mcp": {
      "command": "/absolute/path/to/opentelemetry-mcp-server/start_locally.sh"
    }
  }
}
```

**Pros:**
- Switch backends by editing one file (`start_locally.sh`)
- Centralized configuration
- Includes validation (checks if `uv` is installed)

**Cons:**
- Requires absolute path
- macOS/Linux only (no Windows support yet)

**To switch backends:** Edit `start_locally.sh` and uncomment your preferred backend section.

#### Option 2: Direct Configuration (Standard MCP Pattern)

**Best for:** Production, single backend, Windows users, following MCP ecosystem conventions

##### Jaeger Backend (Local)

```json
{
  "mcpServers": {
    "opentelemetry-mcp-jaeger": {
      "command": "uv",
      "args": [
        "--directory",
        "/absolute/path/to/opentelemetry-mcp-server",
        "run",
        "opentelemetry-mcp"
      ],
      "env": {
        "BACKEND_TYPE": "jaeger",
        "BACKEND_URL": "http://localhost:16686"
      }
    }
  }
}
```

##### Tempo Backend (Local)

```json
{
  "mcpServers": {
    "opentelemetry-mcp-tempo": {
      "command": "uv",
      "args": [
        "--directory",
        "/absolute/path/to/opentelemetry-mcp-server",
        "run",
        "opentelemetry-mcp"
      ],
      "env": {
        "BACKEND_TYPE": "tempo",
        "BACKEND_URL": "http://localhost:3200"
      }
    }
  }
}
```

##### Traceloop Backend (Cloud)

```json
{
  "mcpServers": {
    "opentelemetry-mcp-traceloop": {
      "command": "uv",
      "args": [
        "--directory",
        "/absolute/path/to/opentelemetry-mcp-server",
        "run",
        "opentelemetry-mcp"
      ],
      "env": {
        "BACKEND_TYPE": "traceloop",
        "BACKEND_URL": "https://api.traceloop.com",
        "BACKEND_API_KEY": "your_traceloop_api_key_here"
      }
    }
  }
}
```

**Pros:**
- Standard MCP ecosystem pattern
- Works on all platforms (Windows/macOS/Linux)
- Can configure multiple backends simultaneously (use different server names)
- No wrapper script dependency

**Cons:**
- Must edit JSON config to switch backends
- Backend configuration split between script and config file

**Tip:** You can configure multiple backends at once (e.g., `opentelemetry-mcp-jaeger` and `opentelemetry-mcp-tempo`) and Claude will show both as available MCP servers.

### Best Practices: Choosing an Approach

| Scenario | Recommended Approach | Why |
|----------|---------------------|-----|
| **Development & Testing** | Wrapper Script (`start_locally.sh`) | Easy to switch backends, centralized config |
| **Testing multiple backends** | Wrapper Script | Edit one file to switch, no JSON editing |
| **Production deployment** | Direct Configuration | Standard MCP pattern, explicit configuration |
| **Single backend only** | Direct Configuration | Simpler, no wrapper needed |
| **Windows users** | Direct Configuration | Wrapper script not yet supported on Windows |
| **macOS/Linux users** | Either approach | Choose based on your workflow |
| **Multiple backends simultaneously** | Direct Configuration | Configure all backends with different names |
| **Shared team configuration** | Direct Configuration | More portable, follows MCP conventions |

**General Guidelines:**

- **Start with the wrapper script** if you're testing different backends or doing local development
- **Switch to direct configuration** once you've settled on a backend for production use
- **On Windows**, use direct configuration (wrapper script support coming soon)
- **For CI/CD**, use direct configuration with environment variables
- **For shared teams**, document the direct configuration approach for consistency

**Platform Support:**

- **macOS/Linux**: Both approaches fully supported
- **Windows**: Direct configuration only (PRs welcome for `.bat`/`.ps1` wrapper scripts!)

## Tools Reference

### 1. search_traces

Search for traces with flexible filtering:

```python
{
  "service_name": "my-app",
  "start_time": "2024-01-01T00:00:00Z",
  "end_time": "2024-01-01T23:59:59Z",
  "gen_ai_system": "openai",
  "gen_ai_model": "gpt-4",
  "min_duration_ms": 1000,
  "has_error": false,
  "limit": 50
}
```

**Parameters:**
- `service_name` - Filter by service
- `operation_name` - Filter by operation
- `start_time` / `end_time` - ISO 8601 timestamps
- `min_duration_ms` / `max_duration_ms` - Duration filters
- `gen_ai_system` - LLM provider (openai, anthropic, etc.)
- `gen_ai_model` - Model name (gpt-4, claude-3-opus, etc.)
- `has_error` - Filter by error status
- `tags` - Custom tag filters
- `limit` - Max results (1-1000, default: 100)

**Returns:** List of trace summaries with token counts

### 2. get_trace

Get complete trace details including all spans and OpenLLMetry attributes:

```python
{
  "trace_id": "abc123def456"
}
```

**Returns:** Full trace tree with:
- All spans with attributes
- Parsed OpenLLMetry data for LLM spans
- Token usage per span
- Error information

### 3. get_llm_usage

Get aggregated token usage metrics:

```python
{
  "start_time": "2024-01-01T00:00:00Z",
  "end_time": "2024-01-01T23:59:59Z",
  "service_name": "my-app",
  "gen_ai_system": "openai",
  "limit": 1000
}
```

**Returns:** Aggregated metrics with:
- Total prompt/completion/total tokens
- Breakdown by model
- Breakdown by service
- Request counts

### 4. list_services

List all available services:

```python
{}
```

**Returns:** List of service names

### 5. find_errors

Find traces with errors:

```python
{
  "start_time": "2024-01-01T00:00:00Z",
  "service_name": "my-app",
  "limit": 50
}
```

**Returns:** Error traces with:
- Error messages and types
- Stack traces (truncated)
- LLM-specific error info
- Error span details

## Example Queries

### Find expensive LLM operations

```
Use search_traces to find traces from the last hour where:
- gen_ai_system is "openai"
- min_duration_ms is 5000
```

### Analyze token usage by model

```
Use get_llm_usage for the last 24 hours to see token usage breakdown by model
```

### Debug recent errors

```
Use find_errors to show all error traces from the last hour
```

### Investigate a specific trace

```
Use get_trace with trace_id "abc123" to see all spans and LLM attributes
```

## OpenLLMetry Semantic Conventions

This server automatically parses OpenLLMetry semantic conventions:

### Supported Attributes

- `gen_ai.system` - Provider (openai, anthropic, cohere, etc.)
- `gen_ai.request.model` - Requested model
- `gen_ai.response.model` - Actual model used
- `gen_ai.operation.name` - Operation type (chat, completion, embedding)
- `gen_ai.request.temperature` - Temperature parameter
- `gen_ai.request.top_p` - Top-p parameter
- `gen_ai.request.max_tokens` - Max tokens
- `gen_ai.usage.prompt_tokens` - Input tokens (also supports `input_tokens` for Anthropic)
- `gen_ai.usage.completion_tokens` - Output tokens (also supports `output_tokens` for Anthropic)
- `gen_ai.usage.total_tokens` - Total tokens

### Provider Compatibility

The server handles different token naming conventions:

- **OpenAI**: `prompt_tokens`, `completion_tokens`
- **Anthropic**: `input_tokens`, `output_tokens`
- **Others**: Falls back to standard OpenLLMetry names

## Development

### Running Tests

```bash
# With UV
uv run pytest

# With coverage
uv run pytest --cov=openllmetry_mcp --cov-report=html

# With pip
pytest
```

### Code Quality

```bash
# Format code
uv run ruff format .

# Lint
uv run ruff check .

# Type checking
uv run mypy src/
```

### Project Structure

```
openllmetry-mcp/
   src/openllmetry_mcp/
      __init__.py
      server.py          # Main MCP server
      config.py          # Configuration models
      models.py          # Data models
      backends/          # Backend implementations
         base.py        # Abstract interface
         jaeger.py      # Jaeger backend
         tempo.py       # Tempo backend
         traceloop.py   # Traceloop backend
      tools/             # MCP tools
          search.py
          trace.py
          usage.py
          services.py
          errors.py
   tests/                 # Test suite
   pyproject.toml         # Project configuration
   .env.example           # Example environment config
   README.md
```

## Troubleshooting

### Backend Connection Issues

```bash
# Test backend connectivity
curl http://localhost:16686/api/services  # Jaeger
curl http://localhost:3200/api/search/tags  # Tempo
```

### Authentication Errors

Make sure your API key is set correctly:

```bash
export BACKEND_API_KEY=your_key_here
# Or use --api-key CLI flag
openllmetry-mcp --api-key your_key_here
```

### No Traces Found

- Check time range (use recent timestamps)
- Verify service names with `list_services`
- Check backend has traces: `curl http://localhost:16686/api/services`
- Try searching without filters first

### Token Usage Shows Zero

- Ensure your traces have OpenLLMetry instrumentation
- Check that `gen_ai.usage.*` attributes exist in spans
- Verify with `get_trace` to see raw span attributes

## Future Enhancements

- [ ] Cost calculation with built-in pricing tables
- [ ] Model performance comparison tools
- [ ] Prompt pattern analysis
- [ ] MCP resources for common queries
- [ ] Caching layer for frequent queries
- [ ] Support for additional backends (SigNoz, ClickHouse)

## Contributing

Contributions are welcome! Please ensure:

1. All tests pass: `pytest`
2. Code is formatted: `ruff format .`
3. No linting errors: `ruff check .`
4. Type checking passes: `mypy src/`

## License

MIT License - see LICENSE file for details

## Related Projects

- [OpenLLMetry](https://github.com/traceloop/openllmetry) - OpenTelemetry instrumentation for LLMs
- [Model Context Protocol](https://modelcontextprotocol.io/) - MCP specification
- [Claude Desktop](https://claude.ai/download) - AI assistant with MCP support

## Support

For issues and questions:
- GitHub Issues: https://github.com/yourusername/openllmetry-mcp/issues
- Traceloop Community: https://traceloop.com/slack
