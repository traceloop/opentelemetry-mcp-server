"""Tests for Datadog backend.

Fixtures below are hand-built from Datadog's published OpenAPI spec for the
Spans API (v2) - specifically the `Span`/`SpansAttributes` schema in
https://github.com/DataDog/datadog-api-client-python/blob/master/.generator/schemas/v2/openapi.yaml
- not against a live account (none was available). See the module docstring
in `opentelemetry_mcp/backends/datadog.py` for the two things the public
schema does not pin down (where gen_ai.* attributes land, and how error
status is represented) and how this implementation handles both possibilities
it could find documented.
"""

from collections.abc import Callable
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from opentelemetry_mcp.backends.datadog import _MAX_SEARCH_PAGES, DatadogBackend
from opentelemetry_mcp.models import Filter, FilterOperator, FilterType, SpanQuery

from .conftest import FakeJsonClient

FAKE_API_KEY = "dd-api1"
FAKE_APP_KEY = "dd-app1"


def test_datadog_backend_requires_api_key() -> None:
    """Test that Datadog backend requires an API key."""
    with pytest.raises(ValueError, match="requires an API key"):
        DatadogBackend(url="https://api.datadoghq.com", api_key=None, app_key=FAKE_APP_KEY)


def test_datadog_backend_requires_app_key() -> None:
    """Test that Datadog backend requires an Application key even with an API key."""
    with pytest.raises(ValueError, match="Application key"):
        DatadogBackend(url="https://api.datadoghq.com", api_key=FAKE_API_KEY, app_key=None)


def test_datadog_backend_rejects_non_https_url() -> None:
    """Test that Datadog backend refuses to send credentials over plain http."""
    with pytest.raises(ValueError, match="https://"):
        DatadogBackend(url="http://api.datadoghq.com", api_key=FAKE_API_KEY, app_key=FAKE_APP_KEY)


def test_datadog_client_disables_redirects() -> None:
    """Test that the client never follows redirects (custom credential headers
    are not stripped by httpx on cross-origin redirects)."""
    backend = DatadogBackend(
        url="https://api.datadoghq.com", api_key=FAKE_API_KEY, app_key=FAKE_APP_KEY
    )
    assert backend.client.follow_redirects is False


def test_datadog_backend_initialization() -> None:
    """Test Datadog backend initializes correctly with both keys."""
    backend = DatadogBackend(
        url="https://api.datadoghq.com",
        api_key=FAKE_API_KEY,
        app_key=FAKE_APP_KEY,
        timeout=15.0,
    )

    assert backend.url == "https://api.datadoghq.com"
    assert backend.api_key == FAKE_API_KEY
    assert backend.app_key == FAKE_APP_KEY
    assert backend.timeout == 15.0


def test_datadog_client_headers() -> None:
    """Test that Datadog client sends DD-API-KEY and DD-APPLICATION-KEY headers."""
    backend = DatadogBackend(
        url="https://api.datadoghq.com",
        api_key=FAKE_API_KEY,
        app_key=FAKE_APP_KEY,
    )

    client = backend.client
    assert client.headers["DD-API-KEY"] == FAKE_API_KEY
    assert client.headers["DD-APPLICATION-KEY"] == FAKE_APP_KEY
    assert client.headers["Content-Type"] == "application/json"


def _backend() -> DatadogBackend:
    return DatadogBackend(
        url="https://api.datadoghq.com", api_key=FAKE_API_KEY, app_key=FAKE_APP_KEY
    )


class TestBuildDatadogQuery:
    """Test Filter -> Datadog span search query string conversion."""

    def test_equals_facet_field(self) -> None:
        backend = _backend()
        f = Filter(
            field="service.name",
            operator=FilterOperator.EQUALS,
            value="my-service",
            value_type=FilterType.STRING,
        )
        assert backend._filter_to_dd_query(f) == 'service:"my-service"'

    def test_equals_custom_attribute_is_at_prefixed(self) -> None:
        backend = _backend()
        f = Filter(
            field="gen_ai.system",
            operator=FilterOperator.EQUALS,
            value="openai",
            value_type=FilterType.STRING,
        )
        assert backend._filter_to_dd_query(f) == '@gen_ai.system:"openai"'

    def test_not_equals(self) -> None:
        backend = _backend()
        f = Filter(
            field="gen_ai.system",
            operator=FilterOperator.NOT_EQUALS,
            value="openai",
            value_type=FilterType.STRING,
        )
        assert backend._filter_to_dd_query(f) == '-@gen_ai.system:"openai"'

    def test_status_error_equals(self) -> None:
        backend = _backend()
        f = Filter(
            field="status",
            operator=FilterOperator.EQUALS,
            value="ERROR",
            value_type=FilterType.STRING,
        )
        assert backend._filter_to_dd_query(f) == 'status:"error"'

    def test_status_ok_not_equals(self) -> None:
        """Datadog's status facet is lowercase - a query for -status:"OK"
        would never match anything, so NOT_EQUALS must normalize casing the
        same way EQUALS already does."""
        backend = _backend()
        f = Filter(
            field="status",
            operator=FilterOperator.NOT_EQUALS,
            value="OK",
            value_type=FilterType.STRING,
        )
        assert backend._filter_to_dd_query(f) == '-status:"ok"'

    def test_status_error_not_equals(self) -> None:
        backend = _backend()
        f = Filter(
            field="status",
            operator=FilterOperator.NOT_EQUALS,
            value="ERROR",
            value_type=FilterType.STRING,
        )
        assert backend._filter_to_dd_query(f) == '-status:"error"'

    def test_status_mixed_case_equals_is_lowercased(self) -> None:
        """Filter.value isn't constrained to "OK"/"ERROR" casing - any
        caller-supplied casing must still normalize to Datadog's lowercase
        status facet instead of only exact-matching known literals."""
        backend = _backend()
        f = Filter(
            field="status",
            operator=FilterOperator.EQUALS,
            value="Error",
            value_type=FilterType.STRING,
        )
        assert backend._filter_to_dd_query(f) == 'status:"error"'

    def test_status_mixed_case_not_equals_is_lowercased(self) -> None:
        backend = _backend()
        f = Filter(
            field="status",
            operator=FilterOperator.NOT_EQUALS,
            value="Ok",
            value_type=FilterType.STRING,
        )
        assert backend._filter_to_dd_query(f) == '-status:"ok"'

    def test_status_unset_equals_is_unsupported(self) -> None:
        """ "UNSET" is a value this codebase's own status model allows
        (SpanData.status) but Datadog's status facet only recognizes
        ok/error - a native query for it can never match, so it must be
        rejected here to fall back to client-side filtering rather than
        silently returning zero results."""
        backend = _backend()
        f = Filter(
            field="status",
            operator=FilterOperator.EQUALS,
            value="UNSET",
            value_type=FilterType.STRING,
        )
        assert backend._filter_to_dd_query(f) is None

    def test_status_unset_not_equals_is_unsupported(self) -> None:
        backend = _backend()
        f = Filter(
            field="status",
            operator=FilterOperator.NOT_EQUALS,
            value="UNSET",
            value_type=FilterType.STRING,
        )
        assert backend._filter_to_dd_query(f) is None

    def test_duration_gte_converts_ms_to_ns(self) -> None:
        backend = _backend()
        f = Filter(
            field="duration", operator=FilterOperator.GTE, value=1000, value_type=FilterType.NUMBER
        )
        # 1000ms -> 1_000_000_000ns
        assert backend._filter_to_dd_query(f) == "@duration:[1000000000 TO *]"

    def test_duration_lt_converts_ms_to_ns(self) -> None:
        backend = _backend()
        f = Filter(
            field="duration", operator=FilterOperator.LT, value=5000, value_type=FilterType.NUMBER
        )
        assert backend._filter_to_dd_query(f) == "@duration:{* TO 5000000000}"

    def test_equals_escapes_embedded_quote(self) -> None:
        """A crafted filter value can't inject additional query clauses."""
        backend = _backend()
        f = Filter(
            field="gen_ai.system",
            operator=FilterOperator.EQUALS,
            value='a" OR *:*',
            value_type=FilterType.STRING,
        )
        assert backend._filter_to_dd_query(f) == '@gen_ai.system:"a\\" OR *:*"'

    def test_range_operator_rejects_non_numeric_value(self) -> None:
        """Filter.value_type isn't enforced against the actual Python type,
        so a range operator with a string value must be rejected rather than
        interpolated unchecked into a numeric range expression."""
        backend = _backend()
        f = Filter(
            field="duration",
            operator=FilterOperator.GT,
            value="1000 TO *} OR @duration:{0",
            value_type=FilterType.NUMBER,
        )
        assert backend._filter_to_dd_query(f) is None

    def test_range_operator_rejects_bool_value(self) -> None:
        """bool is an int subclass in Python but not a sensible range operand."""
        backend = _backend()
        f = Filter(
            field="duration", operator=FilterOperator.GTE, value=True, value_type=FilterType.NUMBER
        )
        assert backend._filter_to_dd_query(f) is None

    def test_exists(self) -> None:
        backend = _backend()
        f = Filter(
            field="gen_ai.system", operator=FilterOperator.EXISTS, value_type=FilterType.STRING
        )
        assert backend._filter_to_dd_query(f) == "@gen_ai.system:*"

    def test_not_exists(self) -> None:
        backend = _backend()
        f = Filter(
            field="gen_ai.system", operator=FilterOperator.NOT_EXISTS, value_type=FilterType.STRING
        )
        assert backend._filter_to_dd_query(f) == "-@gen_ai.system:*"

    def test_in_builds_or(self) -> None:
        backend = _backend()
        f = Filter(
            field="gen_ai.system",
            operator=FilterOperator.IN,
            values=["openai", "anthropic"],
            value_type=FilterType.STRING,
        )
        assert backend._filter_to_dd_query(f) == (
            '(@gen_ai.system:"openai" OR @gen_ai.system:"anthropic")'
        )

    def test_in_normalizes_status_casing(self) -> None:
        """IN must lowercase status values the same way EQUALS/NOT_EQUALS
        do - Datadog's status facet is lowercase, so an uppercase term
        would silently never match."""
        backend = _backend()
        f = Filter(
            field="status",
            operator=FilterOperator.IN,
            values=["OK", "ERROR"],
            value_type=FilterType.STRING,
        )
        assert backend._filter_to_dd_query(f) == '(status:"ok" OR status:"error")'

    def test_in_status_unset_is_unsupported(self) -> None:
        """ "UNSET" isn't a real Datadog status facet value - a native
        query for it can never match, so it must be rejected (not silently
        included as an unmatchable OR term)."""
        backend = _backend()
        f = Filter(
            field="status",
            operator=FilterOperator.IN,
            values=["UNSET"],
            value_type=FilterType.STRING,
        )
        assert backend._filter_to_dd_query(f) is None

    def test_in_status_partial_unset_is_unsupported(self) -> None:
        """One unsupported value in the list invalidates the whole native
        IN query - falling back to client-side filtering for all of it
        rather than silently dropping just the bad value from the OR."""
        backend = _backend()
        f = Filter(
            field="status",
            operator=FilterOperator.IN,
            values=["OK", "UNSET"],
            value_type=FilterType.STRING,
        )
        assert backend._filter_to_dd_query(f) is None

    def test_build_dd_query_empty_defaults_to_wildcard(self) -> None:
        backend = _backend()
        assert backend._build_dd_query([]) == ("*", [])

    def test_build_dd_query_joins_with_and(self) -> None:
        backend = _backend()
        filters = [
            Filter(
                field="service.name",
                operator=FilterOperator.EQUALS,
                value="svc",
                value_type=FilterType.STRING,
            ),
            Filter(
                field="gen_ai.system",
                operator=FilterOperator.EQUALS,
                value="openai",
                value_type=FilterType.STRING,
            ),
        ]
        query, unconverted = backend._build_dd_query(filters)
        assert query == 'service:"svc" AND @gen_ai.system:"openai"'
        assert unconverted == []

    def test_build_dd_query_returns_unconverted_filters(self) -> None:
        backend = _backend()
        bad_range_filter = Filter(
            field="duration",
            operator=FilterOperator.GT,
            value="not-a-number",
            value_type=FilterType.NUMBER,
        )
        query, unconverted = backend._build_dd_query([bad_range_filter])
        assert query == "*"
        assert unconverted == [bad_range_filter]


class TestParseDatadogSpan:
    """Test parsing raw Datadog Span resources into SpanData."""

    def test_parse_root_span(self) -> None:
        backend = _backend()
        span_obj = {
            "id": "AAAAAWgN8Xwgr1vKDQAAAABBV2dOOFh3ZzZobm1mWXJFYTR0OA",
            "type": "spans",
            "attributes": {
                "trace_id": "1234567890987654321",
                "span_id": "1234567890987654321",
                "parent_id": "0",
                "service": "my-llm-service",
                "resource_name": "chat_completion",
                "start_timestamp": "2023-01-02T09:42:36.320Z",
                "end_timestamp": "2023-01-02T09:42:36.420Z",
                "tags": ["env:prod", "team:A"],
                "attributes": {
                    "gen_ai.system": "openai",
                    "gen_ai.request.model": "gpt-4",
                    "gen_ai.usage.total_tokens": 150,
                },
            },
        }

        span = backend._parse_dd_span(span_obj)

        assert span is not None
        assert span.trace_id == "1234567890987654321"
        assert span.span_id == "1234567890987654321"
        assert span.parent_span_id is None  # "0" sentinel -> no parent
        assert span.service_name == "my-llm-service"
        assert span.operation_name == "chat_completion"
        assert span.duration_ms == pytest.approx(100.0)
        assert span.status == "UNSET"
        assert span.attributes.gen_ai_system == "openai"
        assert span.attributes.gen_ai_request_model == "gpt-4"

    def test_parse_child_span_with_real_parent(self) -> None:
        backend = _backend()
        span_obj = {
            "id": "child",
            "attributes": {
                "trace_id": "trace1",
                "span_id": "span2",
                "parent_id": "span1",
                "service": "my-service",
                "resource_name": "op",
                "start_timestamp": "2023-01-02T09:42:36.320Z",
                "end_timestamp": "2023-01-02T09:42:36.420Z",
            },
        }

        span = backend._parse_dd_span(span_obj)

        assert span is not None
        assert span.parent_span_id == "span1"

    def test_parse_span_missing_required_ids_returns_none(self) -> None:
        backend = _backend()
        assert backend._parse_dd_span({"attributes": {"service": "svc"}}) is None

    def test_error_inferred_from_custom_attribute(self) -> None:
        backend = _backend()
        span_obj = {
            "attributes": {
                "trace_id": "t1",
                "span_id": "s1",
                "service": "svc",
                "resource_name": "op",
                "start_timestamp": "2023-01-02T09:42:36.320Z",
                "end_timestamp": "2023-01-02T09:42:36.420Z",
                "attributes": {"error": True, "error.message": "boom"},
            },
        }

        span = backend._parse_dd_span(span_obj)

        assert span is not None
        assert span.status == "ERROR"

    def test_error_inferred_from_tag(self) -> None:
        backend = _backend()
        span_obj = {
            "attributes": {
                "trace_id": "t1",
                "span_id": "s1",
                "service": "svc",
                "resource_name": "op",
                "start_timestamp": "2023-01-02T09:42:36.320Z",
                "end_timestamp": "2023-01-02T09:42:36.420Z",
                "tags": ["error:true"],
            },
        }

        span = backend._parse_dd_span(span_obj)

        assert span is not None
        assert span.status == "ERROR"

    def test_nested_gen_ai_attributes_are_flattened(self) -> None:
        """Handles the case where Datadog ingest nests OTel attrs as objects
        rather than flat dotted keys - see module docstring."""
        backend = _backend()
        span_obj = {
            "attributes": {
                "trace_id": "t1",
                "span_id": "s1",
                "service": "svc",
                "resource_name": "op",
                "start_timestamp": "2023-01-02T09:42:36.320Z",
                "end_timestamp": "2023-01-02T09:42:36.420Z",
                "attributes": {"gen_ai": {"system": "anthropic", "request": {"model": "claude"}}},
            },
        }

        span = backend._parse_dd_span(span_obj)

        assert span is not None
        assert span.attributes.gen_ai_system == "anthropic"
        assert span.attributes.gen_ai_request_model == "claude"


class TestGroupIntoTrace:
    """Test grouping a flat span list into TraceData."""

    def test_group_selects_root_and_aggregates_status(self) -> None:
        backend = _backend()
        now = datetime(2023, 1, 2, 9, 42, 36, tzinfo=UTC)

        root = backend._parse_dd_span(
            {
                "attributes": {
                    "trace_id": "t1",
                    "span_id": "root",
                    "parent_id": "0",
                    "service": "svc",
                    "resource_name": "root-op",
                    "start_timestamp": now.isoformat().replace("+00:00", "Z"),
                    "end_timestamp": now.isoformat().replace("+00:00", "Z"),
                }
            }
        )
        child = backend._parse_dd_span(
            {
                "attributes": {
                    "trace_id": "t1",
                    "span_id": "child",
                    "parent_id": "root",
                    "service": "svc",
                    "resource_name": "child-op",
                    "start_timestamp": now.isoformat().replace("+00:00", "Z"),
                    "end_timestamp": now.isoformat().replace("+00:00", "Z"),
                    "attributes": {"error": True},
                }
            }
        )
        assert root is not None and child is not None

        trace = backend._group_into_trace("t1", [root, child])

        assert trace.trace_id == "t1"
        assert trace.service_name == "svc"
        assert trace.root_operation == "root-op"
        assert trace.status == "ERROR"  # child span error propagates to trace status
        assert len(trace.spans) == 2

    def test_group_preserves_unset_when_no_span_confirms_ok_or_error(self) -> None:
        """No span has an explicit error, but none is explicitly OK either -
        the trace status must not silently claim OK."""
        backend = _backend()
        now = datetime(2023, 1, 2, 9, 42, 36, tzinfo=UTC)

        span = backend._parse_dd_span(
            {
                "attributes": {
                    "trace_id": "t2",
                    "span_id": "s1",
                    "service": "svc",
                    "resource_name": "op",
                    "start_timestamp": now.isoformat().replace("+00:00", "Z"),
                    "end_timestamp": now.isoformat().replace("+00:00", "Z"),
                }
            }
        )
        assert span is not None
        assert span.status == "UNSET"

        trace = backend._group_into_trace("t2", [span])

        assert trace.status == "UNSET"


class TestQueryEscaping:
    """Test that untrusted values can't inject additional query clauses."""

    def test_escape_quotes_and_wraps_value(self) -> None:
        backend = _backend()
        assert backend._escape_dd_query_value("abc123") == '"abc123"'

    def test_escape_handles_embedded_quotes(self) -> None:
        backend = _backend()
        assert backend._escape_dd_query_value('a" OR *:*') == '"a\\" OR *:*"'


class TestParseDatadogSpanRejectsBadTimestamps:
    """Test that spans with missing/invalid timing data are rejected rather
    than parsed with fabricated data."""

    def test_missing_end_timestamp_returns_none(self) -> None:
        backend = _backend()
        span_obj = {
            "attributes": {
                "trace_id": "t1",
                "span_id": "s1",
                "service": "svc",
                "resource_name": "op",
                "start_timestamp": "2023-01-02T09:42:36.320Z",
                # end_timestamp missing
            },
        }
        assert backend._parse_dd_span(span_obj) is None

    def test_missing_start_timestamp_returns_none(self) -> None:
        backend = _backend()
        span_obj = {
            "attributes": {
                "trace_id": "t1",
                "span_id": "s1",
                "service": "svc",
                "resource_name": "op",
                "end_timestamp": "2023-01-02T09:42:36.420Z",
                # start_timestamp missing
            },
        }
        assert backend._parse_dd_span(span_obj) is None


class TestGetTraceExactMatch:
    """Test get_trace only keeps spans exactly matching the requested trace_id."""

    async def test_filters_out_non_matching_spans(self) -> None:
        backend = _backend()
        now = "2023-01-02T09:42:36.320Z"
        later = "2023-01-02T09:42:36.420Z"

        backend._search_spans_raw = AsyncMock(  # type: ignore[method-assign]
            return_value=[
                {
                    "attributes": {
                        "trace_id": "requested",
                        "span_id": "s1",
                        "service": "svc",
                        "resource_name": "op",
                        "start_timestamp": now,
                        "end_timestamp": later,
                    }
                },
                {
                    # Wrong trace_id - should be filtered out even though it
                    # came back from the search.
                    "attributes": {
                        "trace_id": "other",
                        "span_id": "s2",
                        "service": "svc",
                        "resource_name": "op",
                        "start_timestamp": now,
                        "end_timestamp": later,
                    }
                },
            ]
        )

        trace = await backend.get_trace("requested")

        assert trace.trace_id == "requested"
        assert len(trace.spans) == 1
        assert trace.spans[0].span_id == "s1"

    async def test_escapes_trace_id_in_query(self) -> None:
        backend = _backend()
        backend._search_spans_raw = AsyncMock(return_value=[])  # type: ignore[method-assign]

        with pytest.raises(ValueError, match="No spans found"):
            await backend.get_trace('evil" OR *:*')

        call_args = backend._search_spans_raw.call_args
        dd_query = call_args.args[0]
        assert dd_query == 'trace_id:"evil\\" OR *:*"'


class TestSearchSpansRawPagination:
    """Test that _search_spans_raw follows Datadog's cursor pagination."""

    async def test_follows_cursor_across_pages(
        self, fake_json_client: Callable[..., FakeJsonClient]
    ) -> None:
        backend = _backend()

        page_1 = {
            "data": [{"attributes": {"span_id": "s1"}}],
            "meta": {"page": {"after": "cursor-1"}},
        }
        page_2 = {
            "data": [{"attributes": {"span_id": "s2"}}],
            "meta": {},  # no cursor -> stop
        }
        backend._client = fake_json_client(page_1, page_2)  # type: ignore[assignment]

        now = datetime(2023, 1, 2, tzinfo=UTC)
        result = await backend._search_spans_raw("*", now, now, limit=2)

        assert [s["attributes"]["span_id"] for s in result] == ["s1", "s2"]

    async def test_stops_at_max_pages_without_infinite_loop(
        self, fake_json_client: Callable[..., FakeJsonClient]
    ) -> None:
        backend = _backend()

        # Always returns a cursor - would loop forever without a cap.
        page = {
            "data": [{"attributes": {"span_id": "s"}}],
            "meta": {"page": {"after": "always-more"}},
        }
        backend._client = fake_json_client(*([page] * _MAX_SEARCH_PAGES))  # type: ignore[assignment]

        now = datetime(2023, 1, 2, tzinfo=UTC)
        result = await backend._search_spans_raw("*", now, now, limit=100_000)

        assert len(result) == 10  # _MAX_SEARCH_PAGES pages x 1 span each

    async def test_malformed_data_field_does_not_crash(
        self, fake_json_client: Callable[..., FakeJsonClient]
    ) -> None:
        """A 200 response whose 'data' field isn't a list (or contains a
        non-dict entry) must not corrupt the collected results."""
        backend = _backend()
        backend._client = fake_json_client({"data": {"unexpected": {}}, "meta": {}})  # type: ignore[assignment]

        now = datetime(2023, 1, 2, tzinfo=UTC)
        result = await backend._search_spans_raw("*", now, now, limit=10)

        assert result == []

    async def test_non_dict_entries_in_data_are_skipped(
        self, fake_json_client: Callable[..., FakeJsonClient]
    ) -> None:
        backend = _backend()
        backend._client = fake_json_client(  # type: ignore[assignment]
            {"data": [{"attributes": {"span_id": "ok"}}, "not-a-span", 123], "meta": {}}
        )

        now = datetime(2023, 1, 2, tzinfo=UTC)
        result = await backend._search_spans_raw("*", now, now, limit=10)

        assert result == [{"attributes": {"span_id": "ok"}}]

    async def test_entry_with_non_dict_attributes_is_skipped(
        self, fake_json_client: Callable[..., FakeJsonClient]
    ) -> None:
        """An item that is itself a dict, but whose 'attributes' value isn't
        one, must also be excluded - every consumer does
        `item.get("attributes", {}).get(...)` directly."""
        backend = _backend()
        backend._client = fake_json_client(  # type: ignore[assignment]
            {
                "data": [{"attributes": {"span_id": "ok"}}, {"attributes": "bad"}],
                "meta": {},
            }
        )

        now = datetime(2023, 1, 2, tzinfo=UTC)
        result = await backend._search_spans_raw("*", now, now, limit=10)

        assert result == [{"attributes": {"span_id": "ok"}}]


class TestGetServiceOperationsEscaping:
    """Test that get_service_operations escapes the service name in its query."""

    async def test_escapes_service_name(self) -> None:
        backend = _backend()
        backend._search_spans_raw = AsyncMock(return_value=[])  # type: ignore[method-assign]

        await backend.get_service_operations('svc" OR *:*')

        call_args = backend._search_spans_raw.call_args
        dd_query = call_args.args[0]
        assert dd_query == 'service:"svc\\" OR *:*"'


class TestGetTraceUsesFullPaginationCapacity:
    """get_trace's contract is "the complete trace" - it should target the
    full pagination capacity, not a single page's worth."""

    async def test_requests_full_pagination_capacity(self) -> None:
        backend = _backend()
        backend._search_spans_raw = AsyncMock(  # type: ignore[method-assign]
            return_value=[
                {
                    "attributes": {
                        "trace_id": "t1",
                        "span_id": "s1",
                        "service": "svc",
                        "resource_name": "op",
                        "start_timestamp": "2023-01-02T09:42:36.320Z",
                        "end_timestamp": "2023-01-02T09:42:36.420Z",
                    }
                }
            ]
        )

        await backend.get_trace("t1")

        call_args = backend._search_spans_raw.call_args
        assert call_args.kwargs.get("limit") == _MAX_SEARCH_PAGES * 1000


class TestSearchSpansRawMalformedEnvelope:
    """Test that a malformed-but-200 response body doesn't crash
    _search_spans_raw at any navigation step (top-level, meta, meta.page)."""

    async def test_non_dict_top_level_body_does_not_crash(
        self, fake_json_client: Callable[..., FakeJsonClient]
    ) -> None:
        backend = _backend()
        backend._client = fake_json_client(["not", "an", "object"])  # type: ignore[assignment]

        now = datetime(2023, 1, 2, tzinfo=UTC)
        result = await backend._search_spans_raw("*", now, now, limit=10)

        assert result == []

    async def test_non_dict_meta_does_not_crash(
        self, fake_json_client: Callable[..., FakeJsonClient]
    ) -> None:
        backend = _backend()
        backend._client = fake_json_client(  # type: ignore[assignment]
            {"data": [{"attributes": {"span_id": "s1"}}], "meta": "not-an-object"}
        )

        now = datetime(2023, 1, 2, tzinfo=UTC)
        result = await backend._search_spans_raw("*", now, now, limit=10)

        # The one valid span is still collected; malformed meta just means
        # "no cursor" rather than a crash.
        assert result == [{"attributes": {"span_id": "s1"}}]

    async def test_non_dict_meta_page_does_not_crash(
        self, fake_json_client: Callable[..., FakeJsonClient]
    ) -> None:
        backend = _backend()
        backend._client = fake_json_client(  # type: ignore[assignment]
            {"data": [{"attributes": {"span_id": "s1"}}], "meta": {"page": "nope"}}
        )

        now = datetime(2023, 1, 2, tzinfo=UTC)
        result = await backend._search_spans_raw("*", now, now, limit=10)

        assert result == [{"attributes": {"span_id": "s1"}}]


class TestSearchSpansFallsBackForUnconvertedNativeFilters:
    """A range filter (GT/GTE/LT/LTE) is classified as natively-supported by
    operator, but _filter_to_dd_query can still reject its operand (e.g.
    non-numeric) and drop it from the query. search_spans must not then
    treat the filter as satisfied - it has to fall back to client-side
    filtering for it, the same as it does for operators Datadog can't
    express at all. Otherwise dd_query silently degrades to "*" and the
    filter is skipped entirely instead of applied or rejected."""

    async def test_bad_range_operand_is_not_silently_dropped(self) -> None:
        backend = _backend()
        now = "2023-01-02T09:42:36.320Z"
        later = "2023-01-02T09:42:36.420Z"
        backend._search_spans_raw = AsyncMock(  # type: ignore[method-assign]
            return_value=[
                {
                    "attributes": {
                        "trace_id": "t1",
                        "span_id": "s1",
                        "service": "svc",
                        "resource_name": "op",
                        "start_timestamp": now,
                        "end_timestamp": later,
                    }
                }
            ]
        )
        query = SpanQuery(
            filters=[
                Filter(
                    field="duration",
                    operator=FilterOperator.GT,
                    value="not-a-number",
                    value_type=FilterType.NUMBER,
                )
            ]
        )

        spans = await backend.search_spans(query)

        # The bad operand made the native query a no-op ("*" - see below),
        # but the filter still must not be treated as satisfied: falling
        # back to client-side evaluation correctly rejects every span
        # instead of returning them all unfiltered.
        assert spans == []
        dd_query = backend._search_spans_raw.call_args.args[0]
        assert dd_query == "*"
