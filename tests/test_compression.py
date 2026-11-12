"""Tests for the compact_json compression utility."""

import pytest

from src.opentelemetry_mcp.tools.compression import compact_json

# ── BASIC COMPRESSION ──────────────────────────────────────────


def test_uniform_array_compresses() -> None:
    """Standard case — array of identical-key dicts gets tabularized."""
    data = [
        {"model": "gpt-4", "provider": "openai", "count": 48},
        {"model": "gpt-3.5", "provider": "openai", "count": 12},
        {"model": "claude", "provider": "anthropic", "count": 5},
    ]
    result = compact_json(data)
    assert result["columns"] == ["model", "provider", "count"]
    assert result["rows"] == [
        ["gpt-4", "openai", 48],
        ["gpt-3.5", "openai", 12],
        ["claude", "anthropic", 5],
    ]


def test_lossless() -> None:
    """Compressed data can be reconstructed back to original."""
    data = [
        {"trace_id": "abc", "model": "gpt-4", "tokens": 100},
        {"trace_id": "def", "model": "gpt-3.5", "tokens": 50},
        {"trace_id": "ghi", "model": "claude", "tokens": 75},
    ]
    result = compact_json(data)
    reconstructed = [dict(zip(result["columns"], row)) for row in result["rows"]]
    assert reconstructed == data


# ── PASS-THROUGH CASES ─────────────────────────────────────────


def test_non_uniform_keys_passthrough() -> None:
    """Arrays where objects have different keys are left alone."""
    data = [{"a": 1}, {"b": 2}]
    assert compact_json(data) == data


def test_missing_keys_passthrough() -> None:
    """Arrays where some objects are missing keys are left alone."""
    data = [
        {"model": "gpt-4", "tokens": 100, "latency": 200},
        {"model": "gpt-3.5", "tokens": 50},
    ]
    assert compact_json(data) == data


def test_empty_array_passthrough() -> None:
    """Empty arrays pass through unchanged."""
    assert compact_json([]) == []


def test_single_item_passthrough() -> None:
    """Single-item lists are not worth compressing."""
    data = [{"model": "gpt-4", "tokens": 100}]
    assert compact_json(data) == data


def test_non_dict_list_passthrough() -> None:
    """Lists of non-dicts pass through unchanged."""
    data = ["gpt-4", "gpt-3.5", "claude"]
    assert compact_json(data) == data


def test_primitive_passthrough() -> None:
    """Primitives pass through unchanged."""
    assert compact_json("hello") == "hello"
    assert compact_json(42) == 42
    assert compact_json(True) is True
    assert compact_json(None) is None


def test_below_threshold_passthrough() -> None:
    """Arrays that don't meet the 5% savings threshold pass through."""
    data = [{"a": 1}, {"a": 2}]
    assert compact_json(data) == data


# ── NESTED STRUCTURES ──────────────────────────────────────────


def test_nested_dict_with_array_compresses() -> None:
    """Arrays nested inside dicts are recursively compressed."""
    data = {
        "count": 2,
        "traces": [
            {"trace_id": "abc", "model": "gpt-4", "tokens": 100},
            {"trace_id": "def", "model": "gpt-3.5", "tokens": 50},
            {"trace_id": "ghi", "model": "claude", "tokens": 75},
        ],
    }
    result = compact_json(data)
    assert result["count"] == 2
    assert "columns" in result["traces"]
    assert "rows" in result["traces"]


def test_multiple_nested_arrays_compress_independently() -> None:
    """Two different nested arrays each get their own columns/rows."""
    data = {
        "traces": [
            {"trace_id": "abc", "tokens": 100},
            {"trace_id": "def", "tokens": 50},
            {"trace_id": "ghi", "tokens": 75},
        ],
        "summary": {
            "by_model": [
                {"model": "gpt-4", "count": 1},
                {"model": "gpt-3.5", "count": 2},
                {"model": "claude", "count": 3},
            ]
        },
    }
    result = compact_json(data)
    assert result["traces"]["columns"] == ["trace_id", "tokens"]
    assert result["summary"]["by_model"]["columns"] == ["model", "count"]


def test_deeply_nested_compression() -> None:
    """Compression works at arbitrary nesting depth."""
    data = {
        "level1": {
            "level2": {
                "items": [
                    {"id": 1, "value": "a"},
                    {"id": 2, "value": "b"},
                    {"id": 3, "value": "c"},
                ]
            }
        }
    }
    result = compact_json(data)
    assert "columns" in result["level1"]["level2"]["items"]


# ── THRESHOLD ──────────────────────────────────────────────────


def test_custom_threshold_respected() -> None:
    """A stricter threshold can prevent compression."""
    data = [
        {"model": "gpt-4", "tokens": 100},
        {"model": "gpt-3.5", "tokens": 50},
        {"model": "claude", "tokens": 75},
    ]
    result = compact_json(data, threshold=1.0)
    assert result == data


def test_threshold_zero_always_compresses() -> None:
    """threshold=0.0 compresses any uniform array where result is smaller."""
    data = [
        {"model": "gpt-4", "provider": "openai", "count": 48},
        {"model": "gpt-3.5", "provider": "openai", "count": 12},
        {"model": "claude", "provider": "anthropic", "count": 5},
    ]
    result = compact_json(data, threshold=0.0)
    assert "columns" in result


# ── REAL TOOL RESPONSE SHAPES ──────────────────────────────────


def test_search_traces_response_shape() -> None:
    """Mirrors the actual search_traces response structure."""
    data = {
        "count": 3,
        "traces": [
            {
                "trace_id": "abc123",
                "service_name": "my-app",
                "duration_ms": 8250,
                "total_tokens": 4523,
                "gen_ai_system": "openai",
                "gen_ai_model": "gpt-4",
            },
            {
                "trace_id": "def456",
                "service_name": "my-app",
                "duration_ms": 3100,
                "total_tokens": 1200,
                "gen_ai_system": "openai",
                "gen_ai_model": "gpt-3.5",
            },
            {
                "trace_id": "ghi789",
                "service_name": "my-app",
                "duration_ms": 5400,
                "total_tokens": 2800,
                "gen_ai_system": "anthropic",
                "gen_ai_model": "claude",
            },
        ],
    }
    result = compact_json(data)
    assert result["count"] == 3
    assert result["traces"]["columns"] == [
        "trace_id",
        "service_name",
        "duration_ms",
        "total_tokens",
        "gen_ai_system",
        "gen_ai_model",
    ]
    assert len(result["traces"]["rows"]) == 3


def test_list_models_response_shape() -> None:
    """Mirrors the actual list_llm_models response structure."""
    data = {
        "count": 3,
        "models": [
            {
                "model": "gpt-4",
                "provider": "openai",
                "request_count": 48,
                "first_seen": "2024-01-01",
                "last_seen": "2024-01-02",
            },
            {
                "model": "gpt-3.5",
                "provider": "openai",
                "request_count": 12,
                "first_seen": "2024-01-01",
                "last_seen": "2024-01-02",
            },
            {
                "model": "claude",
                "provider": "anthropic",
                "request_count": 5,
                "first_seen": "2024-01-01",
                "last_seen": "2024-01-02",
            },
        ],
    }
    result = compact_json(data)
    assert "columns" in result["models"]
    assert "rows" in result["models"]
    assert result["models"]["columns"] == [
        "model",
        "provider",
        "request_count",
        "first_seen",
        "last_seen",
    ]


def test_compress_responses_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """When compress_responses is False, output remains uncompressed."""
    from src.opentelemetry_mcp.config import ServerConfig

    monkeypatch.setenv("COMPRESS_RESPONSES", "false")
    config = ServerConfig.from_env()
    assert config.compress_responses is False

    data = {
        "count": 2,
        "models": [
            {"model": "gpt-4", "provider": "openai", "count": 48},
            {"model": "gpt-3.5", "provider": "openai", "count": 12},
            {"model": "claude", "provider": "anthropic", "count": 5},
        ],
    }

    if config.compress_responses:
        data = compact_json(data)

    assert isinstance(data["models"], list)
    assert isinstance(data["models"][0], dict)
