"""Tests for span link parsing and output."""

import base64
import json
from typing import Any

from opentelemetry_mcp.attributes import SpanLink
from opentelemetry_mcp.backends.jaeger import JaegerBackend
from opentelemetry_mcp.backends.tempo import TempoBackend
from opentelemetry_mcp.models import TraceData
from opentelemetry_mcp.tools.trace import get_trace

PRODUCER_TRACE_HEX = "0102030405060708090a0b0c0d0e0f10"
PRODUCER_TRACE_B64 = base64.b64encode(bytes.fromhex(PRODUCER_TRACE_HEX)).decode()
PRODUCER_SPAN_B64 = base64.b64encode(bytes.fromhex("1112131415161718")).decode()
CONSUMER_TRACE_B64 = base64.b64encode(bytes.fromhex("2122232425262728292a2b2c2d2e2f30")).decode()
CONSUMER_SPAN_B64 = base64.b64encode(bytes.fromhex("3132333435363738")).decode()


def _tempo_trace(links: list[dict[str, Any]] | None) -> dict[str, Any]:
    span: dict[str, Any] = {
        "traceId": CONSUMER_TRACE_B64,
        "spanId": CONSUMER_SPAN_B64,
        "name": "orders.events process",
        "kind": "SPAN_KIND_CONSUMER",
        "startTimeUnixNano": "1700000000000000000",
        "endTimeUnixNano": "1700000000050000000",
        "attributes": [
            {"key": "messaging.destination.name", "value": {"stringValue": "orders.events"}}
        ],
        "status": {},
    }
    if links is not None:
        span["links"] = links
    return {
        "batches": [
            {
                "resource": {
                    "attributes": [{"key": "service.name", "value": {"stringValue": "billing"}}]
                },
                "scopeSpans": [{"spans": [span]}],
            }
        ]
    }


def test_tempo_parses_span_links() -> None:
    backend = TempoBackend(url="http://localhost:3200")
    trace = backend._parse_tempo_trace(
        _tempo_trace(
            [
                {
                    "traceId": PRODUCER_TRACE_B64,
                    "spanId": PRODUCER_SPAN_B64,
                    "attributes": [
                        {"key": "messaging.operation.type", "value": {"stringValue": "publish"}}
                    ],
                }
            ]
        )
    )

    assert trace is not None
    links = trace.spans[0].links
    assert len(links) == 1
    # Linked trace ID is returned in the hex form that get_trace accepts
    assert links[0].trace_id == PRODUCER_TRACE_HEX
    assert links[0].span_id == PRODUCER_SPAN_B64
    assert links[0].attributes == {"messaging.operation.type": "publish"}


def test_tempo_keeps_hex_link_trace_id() -> None:
    backend = TempoBackend(url="http://localhost:3200")
    trace = backend._parse_tempo_trace(
        _tempo_trace([{"traceId": PRODUCER_TRACE_HEX.upper(), "spanId": "1112131415161718"}])
    )

    assert trace is not None
    assert trace.spans[0].links[0].trace_id == PRODUCER_TRACE_HEX


def test_tempo_span_without_links() -> None:
    backend = TempoBackend(url="http://localhost:3200")
    trace = backend._parse_tempo_trace(_tempo_trace(None))

    assert trace is not None
    assert trace.spans[0].links == []


def test_tempo_skips_incomplete_links() -> None:
    backend = TempoBackend(url="http://localhost:3200")
    trace = backend._parse_tempo_trace(
        _tempo_trace([{"traceId": PRODUCER_TRACE_B64}, {"spanId": PRODUCER_SPAN_B64}])
    )

    assert trace is not None
    assert trace.spans[0].links == []


def _jaeger_span(references: list[dict[str, str]]) -> dict[str, Any]:
    return {
        "traceID": "aaaa",
        "spanID": "span1",
        "operationName": "orders.events process",
        "startTime": 1700000000000000,
        "duration": 50000,
        "tags": [],
        "process": {"serviceName": "billing"},
        "references": references,
        "logs": [],
    }


def test_jaeger_follows_from_reference_becomes_link() -> None:
    backend = JaegerBackend(url="http://localhost:16686")
    span = backend._parse_jaeger_span(
        _jaeger_span(
            [
                {
                    "refType": "FOLLOWS_FROM",
                    "traceID": PRODUCER_TRACE_HEX,
                    "spanID": "1112131415161718",
                }
            ]
        ),
        {},
    )

    assert span is not None
    assert span.parent_span_id is None
    assert span.links == [SpanLink(trace_id=PRODUCER_TRACE_HEX, span_id="1112131415161718")]


def test_jaeger_parent_reference_is_not_a_link() -> None:
    backend = JaegerBackend(url="http://localhost:16686")
    span = backend._parse_jaeger_span(
        _jaeger_span(
            [
                {"refType": "CHILD_OF", "traceID": "aaaa", "spanID": "parent1"},
                {"refType": "FOLLOWS_FROM", "traceID": PRODUCER_TRACE_HEX, "spanID": "1112"},
            ]
        ),
        {},
    )

    assert span is not None
    assert span.parent_span_id == "parent1"
    assert [link.span_id for link in span.links] == ["1112"]


def test_jaeger_span_without_references_has_no_links() -> None:
    backend = JaegerBackend(url="http://localhost:16686")
    span = backend._parse_jaeger_span(_jaeger_span([]), {})

    assert span is not None
    assert span.links == []


class _StaticBackend:
    """Minimal stand-in exposing get_trace for the tool."""

    def __init__(self, trace: TraceData) -> None:
        self._trace = trace

    async def get_trace(self, trace_id: str) -> TraceData:
        return self._trace


async def test_get_trace_output_includes_links() -> None:
    backend = TempoBackend(url="http://localhost:3200")
    trace = backend._parse_tempo_trace(
        _tempo_trace(
            [
                {
                    "traceId": PRODUCER_TRACE_B64,
                    "spanId": PRODUCER_SPAN_B64,
                    "attributes": [
                        {"key": "messaging.operation.type", "value": {"stringValue": "publish"}}
                    ],
                }
            ]
        )
    )
    assert trace is not None

    output = json.loads(await get_trace(_StaticBackend(trace), "ignored"))  # type: ignore[arg-type]

    assert output["spans"][0]["links"] == [
        {
            "trace_id": PRODUCER_TRACE_HEX,
            "span_id": PRODUCER_SPAN_B64,
            "attributes": {"messaging.operation.type": "publish"},
        }
    ]


async def test_get_trace_output_omits_links_when_absent() -> None:
    backend = TempoBackend(url="http://localhost:3200")
    trace = backend._parse_tempo_trace(_tempo_trace(None))
    assert trace is not None

    output = json.loads(await get_trace(_StaticBackend(trace), "ignored"))  # type: ignore[arg-type]

    assert "links" not in output["spans"][0]
