# OpenTelemetry MCP Server

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![PyPI](https://img.shields.io/pypi/v/opentelemetry-mcp)](https://pypi.org/project/opentelemetry-mcp/)
[![License](https://img.shields.io/badge/license-Apache%202.0-green.svg)](LICENSE)

**Query and analyze LLM traces with AI assistance.** Ask Claude to find expensive API calls, debug errors, compare model performance, or track token usage—all from your IDE.

An MCP (Model Context Protocol) server that connects AI assistants to OpenTelemetry trace backends (Jaeger, Tempo, Traceloop), with specialized support for LLM observability through OpenLLMetry semantic conventions.

---

## Table of Contents

- [Quick Start](#quick-start)
- [Installation](#installation)
- [Features](#features)
- [Configuration](#configuration)
- [Tools Reference](#tools-reference)
- [Example Queries](#example-queries)
- [Common Workflows](#common-workflows)
- [Troubleshooting](#troubleshooting)
- [Development](#development)
- [Support](#support)

---

## Quick Start

**No installation required!** Configure your client to run the server directly from PyPI:

```json
// Add to claude_desktop_config.json:
{
  "mcpServers": {
    "opentelemetry-mcp": {
      "command": "pipx",
      "args": ["run", "opentelemetry-mcp"],
      "env": {
        "BACKEND_TYPE": "jaeger",
        "BACKEND_URL": "http://localhost:16686"
      }
    }
  }
}
```

Or use `uvx` (alternative):

```json
{
  "mcpServers": {
    "opentelemetry-mcp": {
      "command": "uvx",
      "args": ["opentelemetry-mcp"],
      "env": {
        "BACKEND_TYPE": "jaeger",
        "BACKEND_URL": "http://localhost:16686"
      }
    }
  }
}
```

**That's it!** Ask Claude: _"Show me traces with errors from the last hour"_

---

## Installation

### For End Users (Recommended)

```bash
# Run without installing (recommended)
pipx run opentelemetry-mcp --backend jaeger --url http://localhost:16686

# Or with uvx
uvx opentelemetry-mcp --backend jaeger --url http://localhost:16686
```

This approach:

- ✅ Always uses the latest version
- ✅ No global installation needed
- ✅ Isolated environment automatically
- ✅ Works on all platforms

### Per Client Integration

<details>
<summary><b>Claude Desktop</b></summary>

Configure the MCP server in your Claude Desktop config file:

- **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`

**Using pipx (recommended):**

```json
{
  "mcpServers": {
    "opentelemetry-mcp": {
      "command": "pipx",
      "args": ["run", "opentelemetry-mcp"],
      "env": {
        "BACKEND_TYPE": "jaeger",
        "BACKEND_URL": "http://localhost:16686"
      }
    }
  }
}
```

**Using uvx (alternative):**

```json
{
  "mcpServers": {
    "opentelemetry-mcp": {
      "command": "uvx",
      "args": ["opentelemetry-mcp"],
      "env": {
        "BACKEND_TYPE": "jaeger",
        "BACKEND_URL": "http://localhost:16686"
      }
    }
  }
}
```

**For Traceloop backend:**

```json
{
  "mcpServers": {
    "opentelemetry-mcp": {
      "command": "pipx",
      "args": ["run", "opentelemetry-mcp"],
      "env": {
        "BACKEND_TYPE": "traceloop",
        "BACKEND_URL": "https://api.traceloop.com",
        "BACKEND_API_KEY": "your_traceloop_api_key_here"
      }
    }
  }
}
```

<details>
<summary>Using the repository instead of pipx?</summary>

If you're developing locally with the cloned repository, use one of these configurations:

**Option 1: Wrapper script (easy backend switching)**

```json
{
  "mcpServers": {
    "opentelemetry-mcp": {
      "command": "/absolute/path/to/opentelemetry-mcp-server/start_locally.sh"
    }
  }
}
```

**Option 2: UV directly (for multiple backends)**

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

</details>

</details>

<details>
<summary><b>Claude Code</b></summary>

Claude Code works with MCP servers configured in your Claude Desktop config. Once configured above, you can use the server with Claude Code CLI:

```bash
# Verify the server is available
claude-code mcp list

# Use Claude Code with access to your OpenTelemetry traces
claude-code "Show me traces with errors from the last hour"
```

</details>

<details>
<summary><b>Codeium (Windsurf)</b></summary>

1. Open Windsurf
2. Navigate to **Settings → MCP Servers**
3. Click **Add New MCP Server**
4. Add this configuration:

**Using pipx (recommended):**

```json
{
  "opentelemetry-mcp": {
    "command": "pipx",
    "args": ["run", "opentelemetry-mcp"],
    "env": {
      "BACKEND_TYPE": "jaeger",
      "BACKEND_URL": "http://localhost:16686"
    }
  }
}
```

**Using uvx (alternative):**

```json
{
  "opentelemetry-mcp": {
    "command": "uvx",
    "args": ["opentelemetry-mcp"],
    "env": {
      "BACKEND_TYPE": "jaeger",
      "BACKEND_URL": "http://localhost:16686"
    }
  }
}
```

<details>
<summary>Using the repository instead?</summary>

```json
{
  "opentelemetry-mcp": {
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
```

</details>

</details>

<details>
<summary><b>Cursor</b></summary>

1. Open Cursor
2. Navigate to **Settings → MCP**
3. Click **Add new MCP Server**
4. Add this configuration:

**Using pipx (recommended):**

```json
{
  "opentelemetry-mcp": {
    "command": "pipx",
    "args": ["run", "opentelemetry-mcp"],
    "env": {
      "BACKEND_TYPE": "jaeger",
      "BACKEND_URL": "http://localhost:16686"
    }
  }
}
```

**Using uvx (alternative):**

```json
{
  "opentelemetry-mcp": {
    "command": "uvx",
    "args": ["opentelemetry-mcp"],
    "env": {
      "BACKEND_TYPE": "jaeger",
      "BACKEND_URL": "http://localhost:16686"
    }
  }
}
```

<details>
<summary>Using the repository instead of pipx?</summary>

```json
{
  "opentelemetry-mcp": {
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
```

</details>

</details>

<details>
<summary><b>Gemini CLI</b></summary>

Configure the MCP server in your Gemini CLI config file (`~/.gemini/config.json`):

**Using pipx (recommended):**

```json
{
  "mcpServers": {
    "opentelemetry-mcp": {
      "command": "pipx",
      "args": ["run", "opentelemetry-mcp"],
      "env": {
        "BACKEND_TYPE": "jaeger",
        "BACKEND_URL": "http://localhost:16686"
      }
    }
  }
}
```

**Using uvx (alternative):**

```json
{
  "mcpServers": {
    "opentelemetry-mcp": {
      "command": "uvx",
      "args": ["opentelemetry-mcp"],
      "env": {
        "BACKEND_TYPE": "jaeger",
        "BACKEND_URL": "http://localhost:16686"
      }
    }
  }
}
```

Then use Gemini CLI with your traces:

```bash
gemini "Analyze token usage for gpt-4 requests today"
```

<details>
<parameter name="name">Using the repository instead?</summary>

```json
{
  "mcpServers": {
    "opentelemetry-mcp": {
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

</details>

</details>

**_Prerequisites:_**

- Python 3.11 or higher
- [pipx](https://pipx.pypa.io/) or [uv](https://github.com/astral-sh/uv) installed

<details>
<summary><b>Optional: Install globally</b></summary>

If you prefer to install the command globally:

```bash
# Install with pipx
pipx install opentelemetry-mcp

# Verify
opentelemetry-mcp --help

# Upgrade
pipx upgrade opentelemetry-mcp
```

Or with pip:

```bash
pip install opentelemetry-mcp
```

</details>

## Features

### Core Capabilities

- **🔌 Multiple Backend Support** - Connect to Jaeger, Grafana Tempo, or Traceloop
- **🤖 LLM-First Design** - Specialized tools for analyzing AI application traces
- **🔍 Advanced Filtering** - Generic filter system with powerful operators
- **📊 Token Analytics** - Track and aggregate LLM token usage across models and services
- **⚡ Fast & Type-Safe** - Built with async Python and Pydantic validation

### Tools

| Tool                       | Description                         | Use Case                           |
| -------------------------- | ----------------------------------- | ---------------------------------- |
| `search_traces`            | Search traces with advanced filters | Find specific requests or patterns |
| `search_spans`             | Search individual spans             | Analyze specific operations        |
| `get_trace`                | Get complete trace details          | Deep-dive into a single trace      |
| `get_llm_usage`            | Aggregate token usage metrics       | Track costs and usage trends       |
| `list_services`            | List available services             | Discover what's instrumented       |
| `find_errors`              | Find traces with errors             | Debug failures quickly             |
| `list_llm_models`          | Discover models in use              | Track model adoption               |
| `get_llm_model_stats`      | Get model performance stats         | Compare model efficiency           |
| `get_llm_expensive_traces` | Find highest token usage            | Optimize costs                     |
| `get_llm_slow_traces`      | Find slowest operations             | Improve performance                |

### Backend Support Matrix

| Feature          | Jaeger | Tempo | Traceloop |
| ---------------- | :----: | :---: | :-------: |
| Search traces    |   ✓    |   ✓   |     ✓     |
| Advanced filters |   ✓    |   ✓   |     ✓     |
| Span search      |  ✓\*   |   ✓   |     ✓     |
| Token tracking   |   ✓    |   ✓   |     ✓     |
| Error traces     |   ✓    |   ✓   |     ✓     |
| LLM tools        |   ✓    |   ✓   |     ✓     |

<sub>\* Jaeger requires `service_name` parameter for span search</sub>

### For Developers

If you're contributing to the project or want to make local modifications:

```bash
# Clone the repository
git clone https://github.com/traceloop/opentelemetry-mcp-server.git
cd opentelemetry-mcp-server

# Install dependencies with UV
uv sync

# Or install in development mode with editable install
uv pip install -e ".[dev]"
```

---

## Configuration

### Supported Backends

| Backend       | Type        | URL Example                 | Notes                      |
| ------------- | ----------- | --------------------------- | -------------------------- |
| **Jaeger**    | Local       | `http://localhost:16686`    | Popular open-source option |
| **Tempo**     | Local/Cloud | `http://localhost:3200`     | Grafana's trace backend    |
| **Traceloop** | Cloud       | `https://api.traceloop.com` | Requires API key           |

### Quick Configuration

**Option 1: Environment Variables** (Create `.env` file - see [.env.example](.env.example))

```bash
BACKEND_TYPE=jaeger
BACKEND_URL=http://localhost:16686
```

**Option 2: CLI Arguments** (Override environment)

```bash
opentelemetry-mcp --backend jaeger --url http://localhost:16686
opentelemetry-mcp --backend traceloop --url https://api.traceloop.com --api-key YOUR_KEY
```

> **Configuration Precedence:** CLI arguments > Environment variables > Defaults

<details>
<summary><b>All Configuration Options</b></summary>

| Variable               | Type    | Default  | Description                                        |
| ---------------------- | ------- | -------- | -------------------------------------------------- |
| `BACKEND_TYPE`         | string  | `jaeger` | Backend type: `jaeger`, `tempo`, or `traceloop`    |
| `BACKEND_URL`          | URL     | -        | Backend API endpoint (required)                    |
| `BACKEND_API_KEY`      | string  | -        | API key (required for Traceloop)                   |
| `BACKEND_TIMEOUT`      | integer | `30`     | Request timeout in seconds                         |
| `LOG_LEVEL`            | string  | `INFO`   | Logging level: `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `MAX_TRACES_PER_QUERY` | integer | `100`    | Maximum traces to return per query (1-1000)        |

**Complete `.env` example:**

```bash
# Backend configuration
BACKEND_TYPE=jaeger
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

</details>

<details>
<summary><b>Backend-Specific Setup</b></summary>

### Jaeger

```bash
BACKEND_TYPE=jaeger
BACKEND_URL=http://localhost:16686
```

### Grafana Tempo

```bash
BACKEND_TYPE=tempo
BACKEND_URL=http://localhost:3200
```

### Traceloop

```bash
BACKEND_TYPE=traceloop
BACKEND_URL=https://api.traceloop.com
BACKEND_API_KEY=your_api_key_here
```

> **Note:** The API key contains project information. The backend uses a project slug of `"default"` and Traceloop resolves the actual project/environment from the API key.

</details>

---

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
# If installed with pipx/pip
opentelemetry-mcp

# If running from cloned repository with UV
uv run opentelemetry-mcp

# With backend override (pipx/pip)
opentelemetry-mcp --backend jaeger --url http://localhost:16686

# With backend override (UV)
uv run opentelemetry-mcp --backend jaeger --url http://localhost:16686
```

#### HTTP Transport (for Network Access)

Start the MCP server with HTTP/SSE transport for remote access:

```bash
# If installed with pipx/pip
opentelemetry-mcp --transport http

# If running from cloned repository with UV
uv run opentelemetry-mcp --transport http

# Specify custom host and port (pipx/pip)
opentelemetry-mcp --transport http --host 127.0.0.1 --port 9000

# With UV
uv run opentelemetry-mcp --transport http --host 127.0.0.1 --port 9000
```

The HTTP server will be accessible at `http://localhost:8000/sse` by default.

**Transport Use Cases:**

- **stdio transport**: Local use, Claude Desktop integration, single process
- **HTTP transport**: Remote access, multiple clients, network deployment, sample applications

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

### Find Expensive OpenAI Operations

**Natural Language:** _"Show me OpenAI traces from the last hour that took longer than 5 seconds"_

**Tool Call:** `search_traces`

```json
{
  "service_name": "my-app",
  "gen_ai_system": "openai",
  "min_duration_ms": 5000,
  "start_time": "2024-01-15T10:00:00Z",
  "limit": 20
}
```

**Response:**

```json
{
  "traces": [
    {
      "trace_id": "abc123...",
      "service_name": "my-app",
      "duration_ms": 8250,
      "total_tokens": 4523,
      "gen_ai_system": "openai",
      "gen_ai_model": "gpt-4"
    }
  ],
  "count": 1
}
```

---

### Analyze Token Usage by Model

**Natural Language:** _"How many tokens did we use for each model today?"_

**Tool Call:** `get_llm_usage`

```json
{
  "start_time": "2024-01-15T00:00:00Z",
  "end_time": "2024-01-15T23:59:59Z",
  "service_name": "my-app"
}
```

**Response:**

```json
{
  "summary": {
    "total_tokens": 125430,
    "prompt_tokens": 82140,
    "completion_tokens": 43290,
    "request_count": 487
  },
  "by_model": {
    "gpt-4": {
      "total_tokens": 85200,
      "request_count": 156
    },
    "gpt-3.5-turbo": {
      "total_tokens": 40230,
      "request_count": 331
    }
  }
}
```

---

### Find Traces with Errors

**Natural Language:** _"Show me all errors from the last hour"_

**Tool Call:** `find_errors`

```json
{
  "start_time": "2024-01-15T14:00:00Z",
  "service_name": "my-app",
  "limit": 10
}
```

**Response:**

```json
{
  "errors": [
    {
      "trace_id": "def456...",
      "service_name": "my-app",
      "error_message": "RateLimitError: Too many requests",
      "error_type": "openai.error.RateLimitError",
      "timestamp": "2024-01-15T14:23:15Z"
    }
  ],
  "count": 1
}
```

---

### Compare Model Performance

**Natural Language:** _"What's the performance difference between GPT-4 and Claude?"_

**Tool Call 1:** `get_llm_model_stats` for gpt-4

```json
{
  "model_name": "gpt-4",
  "start_time": "2024-01-15T00:00:00Z"
}
```

**Tool Call 2:** `get_llm_model_stats` for claude-3-opus

```json
{
  "model_name": "claude-3-opus-20240229",
  "start_time": "2024-01-15T00:00:00Z"
}
```

---

### Investigate High Token Usage

**Natural Language:** _"Which requests used the most tokens today?"_

**Tool Call:** `get_llm_expensive_traces`

```json
{
  "limit": 10,
  "start_time": "2024-01-15T00:00:00Z",
  "min_tokens": 5000
}
```

---

## Common Workflows

### Cost Optimization

1. **Identify expensive operations:**

   ```
   Use get_llm_expensive_traces to find high-token requests
   ```

2. **Analyze by model:**

   ```
   Use get_llm_usage to see which models are costing the most
   ```

3. **Investigate specific traces:**
   ```
   Use get_trace with the trace_id to see exact prompts/responses
   ```

### Performance Debugging

1. **Find slow operations:**

   ```
   Use get_llm_slow_traces to identify latency issues
   ```

2. **Check for errors:**

   ```
   Use find_errors to see failure patterns
   ```

3. **Analyze finish reasons:**
   ```
   Use get_llm_model_stats to see if responses are being truncated
   ```

### Model Adoption Tracking

1. **Discover models in use:**

   ```
   Use list_llm_models to see all models being called
   ```

2. **Compare model statistics:**

   ```
   Use get_llm_model_stats for each model to compare performance
   ```

3. **Identify shadow AI:**
   ```
   Look for unexpected models or services in list_llm_models results
   ```

---

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
opentelemetry-mcp --api-key your_key_here
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

Apache 2.0 License - see LICENSE file for details

## Related Projects

- [OpenLLMetry](https://github.com/traceloop/openllmetry) - OpenTelemetry instrumentation for LLMs
- [Model Context Protocol](https://modelcontextprotocol.io/) - MCP specification
- [Claude Desktop](https://claude.ai/download) - AI assistant with MCP support

## Support

For issues and questions:

- GitHub Issues: https://github.com/traceloop/opentelemetry-mcp-server/issues
- PyPI Package: https://pypi.org/project/opentelemetry-mcp/
- Traceloop Community: https://traceloop.com/slack
