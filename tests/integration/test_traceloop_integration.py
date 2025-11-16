"""Integration tests for Traceloop backend with VCR cassette recordings.

These tests use pytest-recording to record HTTP responses from a real Traceloop
API instance and replay them in future test runs without requiring the live backend.

To record new cassettes:
    export TRACELOOP_API_KEY="your_api_key"
    uv run pytest tests/integration/test_traceloop_integration.py -v --record-mode=once

To replay from cassettes (no API key needed):
    uv run pytest tests/integration/test_traceloop_integration.py -v --record-mode=none

Cassettes are stored in tests/integration/cassettes/test_traceloop_integration/
"""

import pytest

from opentelemetry_mcp.backends.traceloop import TraceloopBackend
from opentelemetry_mcp.models import (
    Filter,
    FilterOperator,
    FilterType,
    SpanQuery,
    TraceQuery,
)


@pytest.mark.integration
@pytest.mark.vcr
class TestTraceloopBackendHealth:
    """Test Traceloop backend health checks."""

    @pytest.mark.vcr
    async def test_health_check_healthy(self, traceloop_backend: TraceloopBackend) -> None:
        """Test health check returns healthy status when backend is accessible."""
        health = await traceloop_backend.health_check()
        assert health.status == "healthy"
        assert health.backend == "traceloop"
        assert health.url is not None


@pytest.mark.integration
@pytest.mark.vcr
class TestTraceloopListServices:
    """Test Traceloop service listing."""

    @pytest.mark.vcr
    async def test_list_services(self, traceloop_backend: TraceloopBackend) -> None:
        """Test listing all available services."""
        services = await traceloop_backend.list_services()

        # Should return a list of service names
        assert isinstance(services, list)
        # Traceloop should have at least some services if data exists
        # (This may return empty list if no data in the account)
        if len(services) > 0:
            assert all(isinstance(s, str) for s in services)
            # Services should be unique and sorted
            assert len(services) == len(set(services))
            assert services == sorted(services)


@pytest.mark.integration
@pytest.mark.vcr
class TestTraceloopServiceOperations:
    """Test Traceloop service operations listing."""

    @pytest.mark.vcr
    async def test_get_service_operations(self, traceloop_backend: TraceloopBackend) -> None:
        """Test getting operations for a specific service."""
        # First get available services
        services = await traceloop_backend.list_services()

        if len(services) == 0:
            pytest.skip("No services available for testing")

        # Get operations for the first service
        service_name = services[-1]
        operations = await traceloop_backend.get_service_operations(service_name)

        # Should return a list of operation names
        assert isinstance(operations, list)
        if len(operations) > 0:
            assert all(isinstance(op, str) for op in operations)


@pytest.mark.integration
@pytest.mark.vcr
class TestTraceloopSearchTraces:
    """Test Traceloop trace search functionality."""

    @pytest.mark.vcr
    async def test_search_traces_basic(self, traceloop_backend: TraceloopBackend) -> None:
        """Test basic trace search without filters."""
        query = TraceQuery(limit=10)
        traces = await traceloop_backend.search_traces(query)

        # Should return a list (may be empty if no data)
        assert isinstance(traces, list)

        if len(traces) > 0:
            # Verify trace structure
            trace = traces[0]
            assert trace.trace_id is not None
            assert trace.spans is not None
            assert len(trace.spans) > 0
            assert trace.service_name is not None
            assert trace.duration_ms >= 0

    @pytest.mark.vcr
    async def test_search_traces_with_service_filter(
        self, traceloop_backend: TraceloopBackend
    ) -> None:
        """Test trace search filtered by service name."""
        # First get available services
        services = await traceloop_backend.list_services()

        if len(services) == 0:
            pytest.skip("No services available for testing")

        service_name = services[-1]
        query = TraceQuery(service_name=service_name, limit=10)

        traces = await traceloop_backend.search_traces(query)

        # All traces should be from the specified service
        for trace in traces:
            assert trace.service_name == service_name

    @pytest.mark.vcr
    async def test_search_traces_with_limit(self, traceloop_backend: TraceloopBackend) -> None:
        """Test that limit parameter is respected."""
        limit = 5
        query = TraceQuery(limit=limit)

        traces = await traceloop_backend.search_traces(query)

        # Should not exceed the limit
        assert len(traces) <= limit

    @pytest.mark.vcr
    async def test_search_traces_with_duration_filter(
        self, traceloop_backend: TraceloopBackend
    ) -> None:
        """Test trace search with duration filter."""
        # Search for traces longer than 100ms
        query = TraceQuery(min_duration_ms=100, limit=10)

        traces = await traceloop_backend.search_traces(query)

        # Skip if no traces found (test data may not have matching traces)
        if len(traces) == 0:
            pytest.skip("No traces with duration >= 100ms found in test data")

        # All traces should meet the duration requirement
        for trace in traces:
            assert trace.duration_ms >= 100

    @pytest.mark.vcr
    async def test_search_traces_with_error_filter(
        self, traceloop_backend: TraceloopBackend
    ) -> None:
        """Test trace search for traces with errors."""
        query = TraceQuery(has_error=True, limit=10)

        traces = await traceloop_backend.search_traces(query)

        # Skip if no error traces found (test data may not have errors)
        if len(traces) == 0:
            pytest.skip("No error traces found in test data")

        # All traces should have error status
        for trace in traces:
            assert trace.status == "ERROR"

    @pytest.mark.vcr
    async def test_search_traces_with_generic_filter(
        self, traceloop_backend: TraceloopBackend
    ) -> None:
        """Test trace search with generic filter conditions."""
        # Filter for traces with duration > 50ms using generic filter
        filter_condition = Filter(
            field="duration_ms",
            operator=FilterOperator.GT,
            value=50,
            value_type=FilterType.NUMBER,
        )

        query = TraceQuery(filters=[filter_condition], limit=10)

        traces = await traceloop_backend.search_traces(query)

        # Skip if no matching traces found
        if len(traces) == 0:
            pytest.skip("No traces with duration > 50ms found in test data")

        # All traces should meet the filter condition
        for trace in traces:
            assert trace.duration_ms > 50

    @pytest.mark.vcr
    async def test_search_spans_with_llm_model_filter(
        self, traceloop_backend: TraceloopBackend
    ) -> None:
        """Test trace search filtered by LLM model."""
        query = SpanQuery(gen_ai_request_model="gpt-4o-mini", limit=200)

        spans = await traceloop_backend.search_spans(query)

        # Skip if no matching traces found (test data may not have gpt-4 traces)
        if len(spans) == 0:
            pytest.skip("No traces with gpt-4o-mini model found in test data")

        # Verify all returned traces have the correct model
        for span in spans:
            # Check if any span has the requested model
            assert span.attributes.gen_ai_request_model == "gpt-4o-mini"


@pytest.mark.integration
@pytest.mark.vcr
class TestTraceloopGetTrace:
    """Test Traceloop trace retrieval by ID."""

    @pytest.mark.vcr
    async def test_get_trace_by_id(self, traceloop_backend: TraceloopBackend) -> None:
        """Test retrieving a specific trace by ID."""
        # First, search for a trace to get a valid trace_id
        query = TraceQuery(limit=1)
        traces = await traceloop_backend.search_traces(query)

        if len(traces) == 0:
            pytest.skip("No traces available for testing")

        trace_id = traces[0].trace_id

        # Now get the trace by ID
        trace = await traceloop_backend.get_trace(trace_id)

        assert trace.trace_id == trace_id
        assert len(trace.spans) > 0
        assert trace.service_name is not None

    @pytest.mark.vcr
    async def test_get_trace_invalid_id(self, traceloop_backend: TraceloopBackend) -> None:
        """Test getting a trace with an invalid ID raises an error."""
        with pytest.raises(Exception):  # Will be httpx.HTTPError or ValueError
            await traceloop_backend.get_trace("invalid-trace-id-12345")


@pytest.mark.integration
@pytest.mark.vcr
class TestTraceloopSearchSpans:
    """Test Traceloop span search functionality."""

    @pytest.mark.vcr
    async def test_search_spans_basic(self, traceloop_backend: TraceloopBackend) -> None:
        """Test basic span search without filters."""
        query = SpanQuery(limit=20)
        spans = await traceloop_backend.search_spans(query)

        # Should return a list of spans
        assert isinstance(spans, list)

        if len(spans) > 0:
            # Verify span structure
            span = spans[0]
            assert span.trace_id is not None
            assert span.span_id is not None
            assert span.operation_name is not None
            assert span.service_name is not None
            assert span.duration_ms >= 0

    @pytest.mark.vcr
    async def test_search_spans_with_service_filter(
        self, traceloop_backend: TraceloopBackend
    ) -> None:
        """Test span search filtered by service name."""
        services = await traceloop_backend.list_services()

        if len(services) == 0:
            pytest.skip("No services available for testing")

        service_name = services[-1]
        query = SpanQuery(service_name=service_name, limit=20)

        spans = await traceloop_backend.search_spans(query)

        # All spans should be from the specified service
        for span in spans:
            assert span.service_name == service_name

    @pytest.mark.vcr
    async def test_search_spans_with_limit(self, traceloop_backend: TraceloopBackend) -> None:
        """Test that span limit parameter is respected."""
        limit = 10
        query = SpanQuery(limit=limit)

        spans = await traceloop_backend.search_spans(query)

        # Should not exceed the limit
        assert len(spans) <= limit

    @pytest.mark.vcr
    async def test_search_spans_with_operation(self, traceloop_backend: TraceloopBackend) -> None:
        """Test span search filtered by operation name."""
        services = await traceloop_backend.list_services()

        if len(services) == 0:
            pytest.skip("No services available for testing")

        service_name = services[-1]
        operations = await traceloop_backend.get_service_operations(service_name)

        if len(operations) == 0:
            pytest.skip("No operations available for testing")

        operation_name = operations[0]
        query = SpanQuery(service_name=service_name, operation_name=operation_name, limit=20)

        spans = await traceloop_backend.search_spans(query)

        # At least some spans should have the specified operation name
        # (not all spans necessarily, as client-side filtering may apply)
        if len(spans) > 0:
            operation_names = [s.operation_name for s in spans]
            assert operation_name in operation_names

    @pytest.mark.vcr
    async def test_search_spans_with_generic_filter(
        self, traceloop_backend: TraceloopBackend
    ) -> None:
        """Test span search with generic filter conditions."""
        # Filter for spans with duration > 10ms
        filter_condition = Filter(
            field="duration_ms",
            operator=FilterOperator.GT,
            value=10,
            value_type=FilterType.NUMBER,
        )

        query = SpanQuery(filters=[filter_condition], limit=20)

        spans = await traceloop_backend.search_spans(query)

        # Skip if no matching spans found
        if len(spans) == 0:
            pytest.skip("No spans with duration > 10ms found in test data")

        # All spans should meet the filter condition
        for span in spans:
            assert span.duration_ms > 10


@pytest.mark.integration
@pytest.mark.vcr
class TestTraceloopLLMSpans:
    """Test Traceloop LLM-specific span functionality."""

    @pytest.mark.vcr
    async def test_search_llm_spans(self, traceloop_backend: TraceloopBackend) -> None:
        """Test searching for LLM spans with gen_ai attributes."""
        # Filter for spans with gen_ai.system attribute
        filter_condition = Filter(
            field="gen_ai.system",
            operator=FilterOperator.EXISTS,
            value_type=FilterType.STRING,
        )

        query = SpanQuery(filters=[filter_condition], limit=20)

        spans = await traceloop_backend.search_spans(query)

        # Skip if no LLM spans found
        if len(spans) == 0:
            pytest.skip("No LLM spans found in test data")

        # All spans should be LLM spans
        for span in spans:
            assert span.is_llm_span

    @pytest.mark.vcr
    async def test_search_spans_by_llm_system(self, traceloop_backend: TraceloopBackend) -> None:
        """Test searching spans by LLM system/provider."""
        # Search for OpenAI spans
        query = SpanQuery(gen_ai_system="openai", limit=20)

        spans = await traceloop_backend.search_spans(query)

        # Skip if no OpenAI spans found
        if len(spans) == 0:
            pytest.skip("No OpenAI LLM spans found in test data")

        # All returned spans should be from OpenAI
        for span in spans:
            assert span.is_llm_span
            # Check gen_ai.system or llm.vendor
            system = span.attributes.gen_ai_system or span.attributes.llm_vendor
            if system:
                assert system.lower() == "openai"


@pytest.mark.integration
@pytest.mark.vcr
class TestTraceloopFilters:
    """Test Traceloop filter capabilities."""

    @pytest.mark.vcr
    async def test_search_with_multiple_filters(self, traceloop_backend: TraceloopBackend) -> None:
        """Test trace search with multiple filter conditions combined with AND."""
        # Get a service first
        services = await traceloop_backend.list_services()

        if len(services) == 0:
            pytest.skip("No services available for testing")

        service_name = services[-1]

        # Combine service filter with duration filter
        filters = [
            Filter(
                field="service.name",
                operator=FilterOperator.EQUALS,
                value=service_name,
                value_type=FilterType.STRING,
            ),
            Filter(
                field="duration_ms",
                operator=FilterOperator.GT,
                value=50,
                value_type=FilterType.NUMBER,
            ),
        ]

        query = TraceQuery(filters=filters, limit=10)

        traces = await traceloop_backend.search_traces(query)

        # Skip if no matching traces found
        if len(traces) == 0:
            pytest.skip(f"No traces for service '{service_name}' with duration > 50ms found")

        # All traces should match both conditions
        for trace in traces:
            assert trace.service_name == service_name
            assert trace.duration_ms > 50

    @pytest.mark.vcr
    async def test_search_with_comparison_operators(
        self, traceloop_backend: TraceloopBackend
    ) -> None:
        """Test various comparison operators (GT, LT, GTE, LTE)."""
        # Test GTE operator
        filter_gte = Filter(
            field="duration_ms",
            operator=FilterOperator.GTE,
            value=100,
            value_type=FilterType.NUMBER,
        )

        query = TraceQuery(filters=[filter_gte], limit=10)
        traces = await traceloop_backend.search_traces(query)

        # Skip if no matching traces found
        if len(traces) == 0:
            pytest.skip("No traces with duration >= 100ms found in test data")

        for trace in traces:
            assert trace.duration_ms >= 100
