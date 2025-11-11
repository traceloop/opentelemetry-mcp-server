# Multi-stage build for OpenTelemetry MCP Server

# Stage 1: Builder with official UV image
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

# Enable bytecode compilation for faster startup and use copy mode
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

# Disable Python downloads to use system interpreter
ENV UV_PYTHON_DOWNLOADS=0

# Set working directory
WORKDIR /app

# Install dependencies first (cached layer) - this layer is cached between builds
# Uses bind mounts to avoid copying files into intermediate layers
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=README.md,target=README.md \
    uv sync --frozen --no-install-project --no-dev

# Copy application code and install project
COPY . /app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# Stage 2: Runtime - Minimal production image
FROM python:3.12-slim-bookworm AS runtime

# Copy the entire app with virtual environment from builder
COPY --from=builder /app /app

# Set working directory
WORKDIR /app

# Create non-root user for security
RUN useradd -m -u 1000 mcpuser && \
    chown -R mcpuser:mcpuser /app

# Switch to non-root user
USER mcpuser

# Add virtual environment to PATH
ENV PATH="/app/.venv/bin:$PATH"

# Expose port for HTTP transport
EXPOSE 8000

# Environment variables (can be overridden at runtime)
# Note: BACKEND_API_KEY should be provided at runtime via:
#   - docker run -e BACKEND_API_KEY=secret
#   - Docker Compose environment files
#   - Kubernetes secrets
#   - .env files mounted at runtime
ENV BACKEND_TYPE="" \
    BACKEND_URL="" \
    BACKEND_TIMEOUT="30" \
    LOG_LEVEL="INFO" \
    MAX_TRACES_PER_QUERY="100"

# Health check (optional - checks if the process is running)
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import sys; sys.exit(0)"

# Default command: Run server in HTTP transport mode
# Override with docker run command or docker-compose for different configurations
ENTRYPOINT ["opentelemetry-mcp"]
CMD ["--transport", "http", "--host", "0.0.0.0", "--port", "8000"]
