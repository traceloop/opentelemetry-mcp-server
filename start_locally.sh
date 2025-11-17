#!/bin/bash

# OpenTelemetry MCP Server - Local Startup Script
# This script starts the server in stdio mode for local development

set -e  # Exit on error

# Auto-detect script directory (works regardless of where script is called from)
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

echo "Starting OpenTelemetry MCP Server from: $SCRIPT_DIR" >&2

# Check if uv is installed
if ! command -v uv &> /dev/null; then
    echo "Error: 'uv' is not installed or not in PATH" >&2
    echo "Please install uv: https://github.com/astral-sh/uv" >&2
    exit 1
fi

# ============================================
# Backend Configuration
# ============================================
# Uncomment and configure ONE of the backends below:

## Jaeger (local)
# export BACKEND_TYPE="jaeger"
# export BACKEND_URL="http://localhost:16686"

## Traceloop (cloud)
export BACKEND_TYPE="traceloop"
export BACKEND_URL="https://api-staging.traceloop.com"
export BACKEND_API_KEY="tl_9981e7218948437584e08e7b724304d8"  # Set your API key here or via environment
# export BACKEND_TYPE="traceloop"
# export BACKEND_URL="https://api.traceloop.com"
# export BACKEND_API_KEY="your-api-key-here"  # Set your API key here or via environment

## Tempo (local)
# export BACKEND_TYPE="tempo"
# export BACKEND_URL="http://localhost:3200"

# ============================================
# Optional Configuration
# ============================================
# export LOG_LEVEL="DEBUG"  # DEBUG, INFO, WARNING, ERROR
# export MAX_TRACES_PER_QUERY="100"
# export BACKEND_TIMEOUT="30"

# ============================================
# Start Server
# ============================================
echo "Backend: $BACKEND_TYPE" >&2
echo "URL: $BACKEND_URL" >&2
echo "" >&2

# Start the MCP server in stdio mode (for Claude Desktop/MCP clients)
uv run opentelemetry-mcp --transport stdio --backend "$BACKEND_TYPE" --url "$BACKEND_URL"
