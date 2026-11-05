"""Tests for multi-environment backend routing."""

import json
from unittest.mock import AsyncMock

import pytest
from pydantic import HttpUrl

from opentelemetry_mcp import server
from opentelemetry_mcp.attributes import HealthCheckResponse
from opentelemetry_mcp.backends.base import BaseBackend
from opentelemetry_mcp.config import BackendConfig, ServerConfig


def _make_server_config() -> ServerConfig:
    """Create a server config with two named environments."""
    return ServerConfig(
        backend=BackendConfig(
            type="jaeger",
            url=HttpUrl("http://prod.example.com"),
            backend_urls={
                "prod": HttpUrl("http://prod.example.com"),
                "qa": HttpUrl("http://qa.example.com"),
            },
            default_environment="prod",
        ),
    )


@pytest.fixture
def reset_server_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reset server module globals between tests."""
    monkeypatch.setattr(server, "_backends", {})
    monkeypatch.setattr(server, "_default_environment", "default")
    monkeypatch.setattr(server, "_health_checked", set())
    monkeypatch.setattr(server, "_config", None)


@pytest.fixture
def mock_backends() -> dict[str, BaseBackend]:
    """Two mocked backends with healthy health checks."""
    prod = AsyncMock(spec=BaseBackend)
    prod.health_check = AsyncMock(
        return_value=HealthCheckResponse(
            status="healthy", backend="jaeger", url="http://prod.example.com"
        )
    )
    qa = AsyncMock(spec=BaseBackend)
    qa.health_check = AsyncMock(
        return_value=HealthCheckResponse(
            status="healthy", backend="jaeger", url="http://qa.example.com"
        )
    )
    return {"prod": prod, "qa": qa}


# --- BackendConfig.parse_backend_urls ---


def test_parse_backend_urls_json() -> None:
    """JSON string is parsed into a mapping of environment to URL."""
    result = BackendConfig.parse_backend_urls('{"prod": "http://p", "qa": "http://q"}')
    assert result == {
        "prod": HttpUrl("http://p"),
        "qa": HttpUrl("http://q"),
    }


def test_parse_backend_urls_comma_kv() -> None:
    """Comma-separated name=url pairs are parsed correctly."""
    result = BackendConfig.parse_backend_urls("prod=http://p,qa=http://q")
    assert result == {
        "prod": HttpUrl("http://p"),
        "qa": HttpUrl("http://q"),
    }


def test_parse_backend_urls_single_entry() -> None:
    """A single name=url entry is parsed correctly."""
    result = BackendConfig.parse_backend_urls("prod=http://p")
    assert result == {"prod": HttpUrl("http://p")}


def test_parse_backend_urls_invalid_raises() -> None:
    """Garbage input raises a ValueError."""
    with pytest.raises(ValueError, match="BACKEND_URLS"):
        BackendConfig.parse_backend_urls("not-a-url-format!!")


def test_parse_backend_urls_empty_raises() -> None:
    """An empty mapping is rejected with a clear error."""
    with pytest.raises(ValueError, match="at least one"):
        BackendConfig.parse_backend_urls("{}")


# --- BackendConfig.from_env ---


def test_from_env_single_url_backward_compat(monkeypatch: pytest.MonkeyPatch) -> None:
    """Only BACKEND_URL set: it is keyed under the default environment."""
    monkeypatch.setenv("BACKEND_URL", "http://single.example.com")
    monkeypatch.delenv("BACKEND_URLS", raising=False)
    monkeypatch.delenv("DEFAULT_ENVIRONMENT", raising=False)

    config = BackendConfig.from_env()

    assert config.backend_urls == {"default": HttpUrl("http://single.example.com")}
    assert config.url == HttpUrl("http://single.example.com")
    assert config.default_environment == "default"


def test_from_env_backend_urls_takes_precedence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both BACKEND_URL and BACKEND_URLS set: BACKEND_URLS wins."""
    monkeypatch.setenv("BACKEND_URL", "http://single.example.com")
    monkeypatch.setenv("BACKEND_URLS", '{"prod": "http://prod.example.com"}')
    monkeypatch.delenv("DEFAULT_ENVIRONMENT", raising=False)

    config = BackendConfig.from_env()

    assert config.backend_urls == {"prod": HttpUrl("http://prod.example.com")}


def test_from_env_default_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """DEFAULT_ENVIRONMENT is honoured when set."""
    monkeypatch.setenv(
        "BACKEND_URLS",
        '{"prod": "http://prod.example.com", "qa": "http://qa.example.com"}',
    )
    monkeypatch.setenv("DEFAULT_ENVIRONMENT", "prod")
    monkeypatch.delenv("BACKEND_URL", raising=False)

    config = BackendConfig.from_env()

    assert config.default_environment == "prod"


def test_from_env_default_not_in_backend_urls_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DEFAULT_ENVIRONMENT must name one of the configured environments."""
    monkeypatch.setenv(
        "BACKEND_URLS",
        '{"prod": "http://prod.example.com", "qa": "http://qa.example.com"}',
    )
    monkeypatch.setenv("DEFAULT_ENVIRONMENT", "staging")
    monkeypatch.delenv("BACKEND_URL", raising=False)

    with pytest.raises(ValueError, match="staging"):
        BackendConfig.from_env()


def test_from_env_bare_backend_urls_defaults_to_first_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bare BACKEND_URLS without DEFAULT_ENVIRONMENT defaults to the first env."""
    monkeypatch.setenv(
        "BACKEND_URLS",
        '{"prod": "http://prod.example.com", "qa": "http://qa.example.com"}',
    )
    monkeypatch.delenv("BACKEND_URL", raising=False)
    monkeypatch.delenv("DEFAULT_ENVIRONMENT", raising=False)

    config = BackendConfig.from_env()

    assert config.default_environment == "prod"


# --- ServerConfig.apply_cli_overrides ---


def test_apply_cli_overrides_backend_url_updates_backend_urls() -> None:
    """--url replaces the default environment's URL in backend_urls."""
    config = _make_server_config()

    config.apply_cli_overrides(backend_url="http://new-default.example.com")

    assert config.backend.backend_urls["prod"] == HttpUrl("http://new-default.example.com")
    assert config.backend.backend_urls["qa"] == HttpUrl("http://qa.example.com")


def test_apply_cli_overrides_backend_urls_takes_precedence_over_backend_url() -> None:
    """--backend-urls is applied last and wins over --url."""
    config = _make_server_config()

    config.apply_cli_overrides(
        backend_url="http://ignored.example.com",
        backend_urls="prod=http://cli-prod.example.com,qa=http://cli-qa.example.com",
    )

    assert config.backend.backend_urls == {
        "prod": HttpUrl("http://cli-prod.example.com"),
        "qa": HttpUrl("http://cli-qa.example.com"),
    }


# --- server._get_backend routing ---


def _configure_mocks(
    monkeypatch: pytest.MonkeyPatch, mock_backends: dict[str, BaseBackend]
) -> None:
    monkeypatch.setattr(server, "_config", _make_server_config())
    monkeypatch.setattr(server, "_create_backends", lambda config: mock_backends)


async def test_get_backend_routes_to_environment(
    monkeypatch: pytest.MonkeyPatch,
    reset_server_state: None,
    mock_backends: dict[str, BaseBackend],
) -> None:
    """`_get_backend('qa')` returns the backend for the qa environment."""
    _configure_mocks(monkeypatch, mock_backends)

    backend = await server._get_backend("qa")

    assert backend is mock_backends["qa"]


async def test_get_backend_uses_default(
    monkeypatch: pytest.MonkeyPatch,
    reset_server_state: None,
    mock_backends: dict[str, BaseBackend],
) -> None:
    """`_get_backend(None)` returns the default environment's backend."""
    _configure_mocks(monkeypatch, mock_backends)

    backend = await server._get_backend()

    assert backend is mock_backends["prod"]


async def test_get_backend_unknown_env_raises(
    monkeypatch: pytest.MonkeyPatch,
    reset_server_state: None,
    mock_backends: dict[str, BaseBackend],
) -> None:
    """Unknown environments raise a ValueError listing the available ones."""
    _configure_mocks(monkeypatch, mock_backends)

    with pytest.raises(ValueError) as exc_info:
        await server._get_backend("staging")

    message = str(exc_info.value)
    assert "staging" in message
    assert "prod" in message
    assert "qa" in message


async def test_get_backend_health_checks_only_selected(
    monkeypatch: pytest.MonkeyPatch,
    reset_server_state: None,
    mock_backends: dict[str, BaseBackend],
) -> None:
    """Only the selected environment is health-checked on first use."""
    _configure_mocks(monkeypatch, mock_backends)

    backend = await server._get_backend("qa")

    assert backend is mock_backends["qa"]
    mock_backends["qa"].health_check.assert_awaited_once()
    mock_backends["prod"].health_check.assert_not_called()


# --- list_environments tool ---


async def test_list_environments_tool(
    monkeypatch: pytest.MonkeyPatch,
    reset_server_state: None,
    mock_backends: dict[str, BaseBackend],
) -> None:
    """list_environments returns sorted env names and the default environment."""
    _configure_mocks(monkeypatch, mock_backends)

    result = await server.list_environments()

    data = json.loads(result)
    assert data["environments"] == ["prod", "qa"]
    assert data["default_environment"] == "prod"
