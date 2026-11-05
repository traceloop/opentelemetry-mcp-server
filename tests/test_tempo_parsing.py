"""Tests for parsing OTLP trace payloads returned by Tempo."""

from typing import Any

from opentelemetry_mcp.backends.tempo import TempoBackend

SECOND_NS = 1_000_000_000


def make_otlp_span(
    span_id: str, parent_span_id: str | None, service: str, start_s: int
) -> dict[str, Any]:
    """Build one OTLP span as Tempo returns it."""
    span: dict[str, Any] = {
        "traceId": "trace1",
        "spanId": span_id,
        "name": f"op-{span_id}",
        "startTimeUnixNano": str(start_s * SECOND_NS),
        "endTimeUnixNano": str((start_s + 1) * SECOND_NS),
    }
    if parent_span_id:
        span["parentSpanId"] = parent_span_id
    return span


def make_otlp_trace(spans_by_service: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    """Build an OTLP trace payload, one batch per service."""
    return {
        "batches": [
            {
                "resource": {
                    "attributes": [{"key": "service.name", "value": {"stringValue": service}}]
                },
                "scopeSpans": [{"spans": spans}],
            }
            for service, spans in spans_by_service.items()
        ]
    }


def test_parses_true_root_from_otlp() -> None:
    """A trace containing its root reports that root and flags nothing."""
    backend = TempoBackend(url="http://tempo.invalid")
    data = make_otlp_trace(
        {
            "gateway": [make_otlp_span("root", None, "gateway", start_s=0)],
            "worker": [make_otlp_span("child", "root", "worker", start_s=1)],
        }
    )

    trace = backend._parse_tempo_trace(data, trace_id_hex="trace1")

    assert trace is not None
    assert trace.root_operation == "op-root"
    assert trace.service_name == "gateway"
    assert trace.root_is_inferred is False
    assert trace.missing_root_parent_span_id is None


def test_infers_root_when_tempo_returns_a_trace_whose_root_is_still_open() -> None:
    """A trace whose root has not been exported reports the earliest orphan.

    Tempo indexes a trace from the spans received so far, so a trace whose root
    is still open is fetchable while it grows. Every span it holds has a parent,
    and the first batch is not ordered by time, so batch order must not decide
    which span is reported as the root.
    """
    backend = TempoBackend(url="http://tempo.invalid")
    data = make_otlp_trace(
        {
            # Listed first, started last: reporting batch order would pick this.
            "worker": [make_otlp_span("late", "unexported-root", "worker", start_s=30)],
            "gateway": [
                make_otlp_span("early", "unexported-root", "gateway", start_s=0),
                make_otlp_span("child-of-early", "early", "gateway", start_s=2),
            ],
        }
    )

    trace = backend._parse_tempo_trace(data, trace_id_hex="trace1")

    assert trace is not None
    assert trace.root_operation == "op-early"
    assert trace.service_name == "gateway"
    assert trace.root_is_inferred is True
    assert trace.missing_root_parent_span_id == "unexported-root"
