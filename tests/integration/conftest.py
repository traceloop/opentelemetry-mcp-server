"""Fixtures and configuration for integration tests with VCR recordings."""

import os
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from vcr.request import Request

from opentelemetry_mcp.backends.jaeger import JaegerBackend
from opentelemetry_mcp.backends.tempo import TempoBackend
from opentelemetry_mcp.backends.traceloop import TraceloopBackend
from opentelemetry_mcp.config import BackendConfig


def filter_tempo_timestamps(request: Request) -> Request:
    """Remove timestamp query parameters from Tempo requests for better matching.

    Tempo queries include dynamic `start` and `end` timestamp parameters that
    change on every run. This filter removes them from the recorded cassette
    so that future replays will match.

    Args:
        request: VCR Request object

    Returns:
        Modified Request object
    """
    # Parse the URI to remove timestamp parameters
    try:
        url = urlparse(request.uri)
        if "/api/search" in url.path:
            # Parse query parameters
            params = parse_qs(url.query)
            # Remove timestamp parameters
            params.pop("start", None)
            params.pop("end", None)
            # Rebuild query string
            from urllib.parse import urlencode

            new_query = urlencode(params, doseq=True)
            # Rebuild URI with query parameters
            new_url = url._replace(query=new_query)
            # Update the request URI
            request.uri = new_url.geturl()
    except Exception:
        # If anything fails, just return the original request
        pass

    return request


def filter_sensitive_headers(response: dict[str, Any]) -> dict[str, Any]:
    """Remove sensitive headers from cassette recordings only.

    This function filters sensitive headers from the recorded cassette file
    AFTER the actual HTTP request has been made. This allows real API keys
    to be used during recording while keeping them out of version control.

    IMPORTANT: This only filters the cassette file, not the actual HTTP request.

    Args:
        response: VCR response dict containing request and response data

    Returns:
        Modified response dict with filtered headers
    """
    # Filter sensitive request headers
    request_headers = response.get("request", {}).get("headers", {})
    for header in ["authorization", "x-api-key", "cookie"]:
        if header in request_headers:
            request_headers[header] = ["FILTERED"]

    # Filter sensitive response headers
    response_headers = response.get("response", {}).get("headers", {})
    for header in ["set-cookie"]:
        if header in response_headers:
            response_headers[header] = ["FILTERED"]

    return response


@pytest.fixture(scope="module")
def vcr_config(request: pytest.FixtureRequest) -> dict[str, Any]:
    """
    VCR configuration for all integration tests.

    This configuration:
    - Filters sensitive headers from cassettes (not from actual requests!)
    - Records once and replays from cassettes
    - Matches requests by method, scheme, host, port, path, and query
    - Allows replaying the same cassette multiple times
    - Filters timestamp parameters for Tempo tests

    IMPORTANT: We use before_record_response to filter sensitive data from
    cassettes AFTER the request is made, so real API keys work during recording.
    """
    # Check if this is a Tempo test
    is_tempo_test = "tempo" in request.node.nodeid.lower()

    config: dict[str, Any] = {
        # Record mode:
        # - "once": Record if cassette doesn't exist, replay otherwise (default)
        # - "none": Never record, only replay (CI mode)
        # - "new_episodes": Record new requests, replay existing
        # - "all": Always record (rewrite cassettes)
        "record_mode": "once",
        # Don't ignore localhost - we need to record local backend requests
        "ignore_localhost": False,
        # Match requests by these criteria
        "match_on": ["method", "scheme", "host", "port", "path", "query"],
        # Allow replaying same cassette multiple times in one test
        "allow_playback_repeats": True,
        # Decode compressed responses for better cassette readability
        "decode_compressed_response": True,
        # Filter sensitive headers from cassettes AFTER recording (not from requests!)
        "before_record_response": filter_sensitive_headers,
    }

    # For Tempo tests, don't match on query parameters since they include timestamps
    if is_tempo_test:
        config["match_on"] = ["method", "scheme", "host", "port", "path"]
        config["before_record_request"] = filter_tempo_timestamps

    return config


# Jaeger Backend Fixtures


@pytest.fixture
def jaeger_url() -> str:
    """Jaeger backend URL - can be overridden via environment variable."""
    return os.getenv("JAEGER_URL", "http://localhost:16686")


@pytest.fixture
def jaeger_config(jaeger_url: str) -> BackendConfig:
    """Jaeger backend configuration."""
    return BackendConfig(type="jaeger", url=jaeger_url)


@pytest.fixture
async def jaeger_backend(jaeger_config: BackendConfig) -> JaegerBackend:
    """
    Jaeger backend instance for integration testing.

    Uses async context manager to properly initialize and cleanup the backend.
    """
    backend = JaegerBackend(
        url=str(jaeger_config.url), api_key=jaeger_config.api_key, timeout=jaeger_config.timeout
    )
    async with backend:
        yield backend


# Tempo Backend Fixtures


@pytest.fixture
def tempo_url() -> str:
    """Tempo backend URL - can be overridden via environment variable."""
    return os.getenv("TEMPO_URL", "http://localhost:3200")


@pytest.fixture
def tempo_config(tempo_url: str) -> BackendConfig:
    """Tempo backend configuration."""
    return BackendConfig(type="tempo", url=tempo_url)


@pytest.fixture
async def tempo_backend(tempo_config: BackendConfig) -> TempoBackend:
    """
    Tempo backend instance for integration testing.

    Uses async context manager to properly initialize and cleanup the backend.
    """
    backend = TempoBackend(
        url=str(tempo_config.url), api_key=tempo_config.api_key, timeout=tempo_config.timeout
    )
    async with backend:
        yield backend


# Traceloop Backend Fixtures


@pytest.fixture
def traceloop_url() -> str:
    """Traceloop backend URL - can be overridden via environment variable."""
    return os.getenv("TRACELOOP_BASE_URL", "https://api.traceloop.com")


@pytest.fixture
def traceloop_api_key() -> str:
    """
    Traceloop API key - MUST be set via environment variable.

    For recording new cassettes, set TRACELOOP_API_KEY environment variable.
    For replaying cassettes, the key is not needed (filtered from cassettes).
    """
    return os.getenv("TRACELOOP_API_KEY", "test_api_key_for_replay")


@pytest.fixture
def traceloop_config(traceloop_url: str, traceloop_api_key: str) -> BackendConfig:
    """Traceloop backend configuration."""
    return BackendConfig(type="traceloop", url=traceloop_url, api_key=traceloop_api_key)


@pytest.fixture
async def traceloop_backend(traceloop_config: BackendConfig) -> TraceloopBackend:
    """
    Traceloop backend instance for integration testing.

    Uses async context manager to properly initialize and cleanup the backend.
    """
    backend = TraceloopBackend(
        url=str(traceloop_config.url),
        api_key=traceloop_config.api_key,
        timeout=traceloop_config.timeout,
    )
    async with backend:
        yield backend
