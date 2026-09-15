"""Tests for root span resolution on complete and incomplete traces."""

from datetime import datetime, timedelta

import pytest

from opentelemetry_mcp.models import SpanData, resolve_root_span

BASE_TIME = datetime(2024, 1, 1, 12, 0, 0)


def make_span(span_id: str, parent_span_id: str | None, offset_s: float = 0.0) -> SpanData:
    """Build a span with the given parent link and start offset."""
    return SpanData(
        trace_id="trace1",
        span_id=span_id,
        parent_span_id=parent_span_id,
        operation_name=f"op-{span_id}",
        service_name=f"service-{span_id}",
        start_time=BASE_TIME + timedelta(seconds=offset_s),
        duration_ms=10,
    )


def test_resolves_parentless_span_as_true_root() -> None:
    """A span with no parent is the root."""
    spans = [
        make_span("child", "root", offset_s=1),
        make_span("root", None, offset_s=0),
    ]

    resolution = resolve_root_span(spans)

    assert resolution.span.span_id == "root"
    assert resolution.is_true_root is True
    assert resolution.missing_parent_span_id is None


def test_prefers_earliest_when_several_spans_are_parentless() -> None:
    """Several parentless spans resolve to the earliest one, not list order."""
    spans = [
        make_span("late", None, offset_s=5),
        make_span("early", None, offset_s=0),
    ]

    resolution = resolve_root_span(spans)

    assert resolution.span.span_id == "early"
    assert resolution.is_true_root is True


def test_infers_root_when_the_real_root_was_never_received() -> None:
    """Without a parentless span, the earliest orphan stands in for the root."""
    # Every span descends from "unexported", which is not in the trace.
    spans = [
        make_span("grandchild", "orphan-late", offset_s=3),
        make_span("orphan-late", "unexported", offset_s=2),
        make_span("orphan-early", "unexported", offset_s=1),
    ]

    resolution = resolve_root_span(spans)

    assert resolution.span.span_id == "orphan-early"
    assert resolution.is_true_root is False
    assert resolution.missing_parent_span_id == "unexported"


def test_inferred_root_is_not_merely_the_first_span_in_the_list() -> None:
    """The regression: list order must not decide the root."""
    spans = [
        make_span("first-in-list", "orphan", offset_s=9),
        make_span("orphan", "unexported", offset_s=0),
    ]

    resolution = resolve_root_span(spans)

    assert resolution.span.span_id == "orphan"
    assert resolution.is_true_root is False


def test_single_orphan_span_trace() -> None:
    """A trace holding one span whose parent is missing still resolves."""
    spans = [make_span("only", "unexported")]

    resolution = resolve_root_span(spans)

    assert resolution.span.span_id == "only"
    assert resolution.is_true_root is False
    assert resolution.missing_parent_span_id == "unexported"


def test_cyclic_parent_links_fall_back_to_earliest_span() -> None:
    """Parent links that form a cycle report a root rather than failing."""
    spans = [
        make_span("b", "a", offset_s=1),
        make_span("a", "b", offset_s=0),
    ]

    resolution = resolve_root_span(spans)

    assert resolution.span.span_id == "a"
    assert resolution.is_true_root is False
    # Both parents are present, so no parent is missing and none is named.
    assert resolution.missing_parent_span_id is None


def test_ties_on_start_time_do_not_depend_on_list_order() -> None:
    """Spans sharing a start time resolve the same way whatever order they arrive in."""
    first = make_span("aaa", "unexported", offset_s=0)
    second = make_span("bbb", "unexported", offset_s=0)

    forwards = resolve_root_span([first, second])
    backwards = resolve_root_span([second, first])

    assert forwards.span.span_id == backwards.span.span_id == "aaa"


def test_empty_span_list_is_rejected() -> None:
    """An empty trace has no root to resolve."""
    with pytest.raises(ValueError, match="empty span list"):
        resolve_root_span([])
