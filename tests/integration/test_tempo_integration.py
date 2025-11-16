"""Integration tests for Tempo backend using VCR recordings."""

import pytest

from opentelemetry_mcp.backends.tempo import TempoBackend
from opentelemetry_mcp.models import Filter, FilterOperator, FilterType, SpanQuery, TraceQuery

# Mark all tests in this module as integration and vcr
pytestmark = [pytest.mark.integration, pytest.mark.vcr]


class TestTempoBackendHealth:
    """Test Tempo backend health check."""

    @pytest.mark.vcr
    async def test_health_check_healthy(self, tempo_backend: TempoBackend) -> None:
        """Test health check against a healthy Tempo instance."""
        health = await tempo_backend.health_check()

        assert health.status == "healthy"
        assert health.backend == "tempo"
        assert health.url is not None
        # Tempo health check may not return service count
        assert health.service_count is None or health.service_count >= 0


class TestTempoListServices:
    """Test Tempo service listing."""

    @pytest.mark.vcr
    async def test_list_services(self, tempo_backend: TempoBackend) -> None:
        """Test listing all services from Tempo."""
        services = await tempo_backend.list_services()

        assert isinstance(services, list)
        # Services should be strings
        for service in services:
            assert isinstance(service, str)
            assert len(service) > 0


class TestTempoServiceOperations:
    """Test Tempo service operations listing."""

    @pytest.mark.vcr
    async def test_get_service_operations(self, tempo_backend: TempoBackend) -> None:
        """Test getting operations for a specific service."""
        # First, get available services
        services = await tempo_backend.list_services()
        if len(services) == 0:
            pytest.skip("No services available for testing")

        # Get operations for the first service
        service_name = services[0]
        operations = await tempo_backend.get_service_operations(service_name)

        assert isinstance(operations, list)
        # Operations should be strings
        for operation in operations:
            assert isinstance(operation, str)
            assert len(operation) > 0


class TestTempoSearchTraces:
    """Test Tempo trace search functionality with TraceQL."""

    @pytest.mark.vcr
    async def test_search_traces_basic(self, tempo_backend: TempoBackend) -> None:
        """Test basic trace search."""
        query = TraceQuery(limit=10)

        traces = await tempo_backend.search_traces(query)

        assert isinstance(traces, list)
        # Tempo might return empty results if no traces match
        # Each trace should have required fields
        for trace in traces:
            assert trace.trace_id
            assert trace.service_name
            assert trace.spans
            assert len(trace.spans) > 0
            assert trace.start_time
            assert trace.duration_ms >= 0

    @pytest.mark.vcr
    async def test_search_traces_with_service_filter(self, tempo_backend: TempoBackend) -> None:
        """Test trace search filtered by service name."""
        services = await tempo_backend.list_services()
        if len(services) == 0:
            pytest.skip("No services available for testing")

        service_name = services[0]
        query = TraceQuery(service_name=service_name, limit=10)

        traces = await tempo_backend.search_traces(query)

        # All traces should have the specified service (or be empty)
        for trace in traces:
            assert trace.service_name == service_name

    @pytest.mark.vcr
    async def test_search_traces_with_limit(self, tempo_backend: TempoBackend) -> None:
        """Test trace search with result limit."""
        query = TraceQuery(limit=5)

        traces = await tempo_backend.search_traces(query)

        assert len(traces) <= 5

    @pytest.mark.vcr
    async def test_search_traces_with_operation(self, tempo_backend: TempoBackend) -> None:
        """Test trace search filtered by operation name."""
        services = await tempo_backend.list_services()
        if len(services) == 0:
            pytest.skip("No services available for testing")

        service_name = services[0]

        # Get operations for this service
        operations = await tempo_backend.get_service_operations(service_name)
        if len(operations) == 0:
            pytest.skip("No operations available for testing")

        operation_name = operations[0]
        query = TraceQuery(service_name=service_name, operation_name=operation_name, limit=10)

        traces = await tempo_backend.search_traces(query)

        # All traces should have at least one span with the specified operation
        for trace in traces:
            operation_names = [span.operation_name for span in trace.spans]
            assert operation_name in operation_names

    @pytest.mark.vcr
    async def test_search_traces_with_duration_filter(self, tempo_backend: TempoBackend) -> None:
        """Test trace search with minimum duration filter."""
        min_duration_ms = 100  # 100ms minimum

        query = TraceQuery(min_duration_ms=min_duration_ms, limit=10)

        traces = await tempo_backend.search_traces(query)

        # All traces should have duration >= min_duration_ms
        for trace in traces:
            assert trace.duration_ms >= min_duration_ms

    @pytest.mark.vcr
    async def test_search_traces_with_error_filter(self, tempo_backend: TempoBackend) -> None:
        """Test trace search filtered by error status."""
        query = TraceQuery(has_error=True, limit=10)

        traces = await tempo_backend.search_traces(query)

        # All traces should have at least one span with error
        for trace in traces:
            assert any(span.has_error for span in trace.spans)

    @pytest.mark.vcr
    async def test_search_traces_with_generic_filter(self, tempo_backend: TempoBackend) -> None:
        """Test trace search with generic filter conditions (TraceQL)."""
        # Filter for traces with duration > 50ms using TraceQL
        filter_condition = Filter(
            field="duration_ms", operator=FilterOperator.GT, value=50, value_type=FilterType.NUMBER
        )

        query = TraceQuery(filters=[filter_condition], limit=10)

        traces = await tempo_backend.search_traces(query)

        # All traces should meet the filter condition
        for trace in traces:
            assert trace.duration_ms > 50

    @pytest.mark.vcr
    async def test_search_traces_with_attribute_filter(self, tempo_backend: TempoBackend) -> None:
        """Test trace search with attribute existence filter (TraceQL)."""
        # Filter for traces with gen_ai.system attribute
        filter_condition = Filter(
            field="gen_ai.system", operator=FilterOperator.EXISTS, value_type=FilterType.STRING
        )

        query = TraceQuery(filters=[filter_condition], limit=10)

        traces = await tempo_backend.search_traces(query)

        # All traces should have at least one LLM span
        for trace in traces:
            llm_spans = [s for s in trace.spans if s.is_llm_span]
            assert len(llm_spans) > 0


class TestTempoGetTrace:
    """Test Tempo get trace by ID functionality."""

    @pytest.mark.vcr
    async def test_get_trace_by_id(self, tempo_backend: TempoBackend) -> None:
        """Test retrieving a specific trace by ID."""
        # First, search for a trace to get a valid trace_id
        query = TraceQuery(limit=1)
        traces = await tempo_backend.search_traces(query)

        if len(traces) == 0:
            pytest.skip("No traces available for testing")

        trace_id = traces[0].trace_id

        # Now get the trace by ID
        trace = await tempo_backend.get_trace(trace_id)

        assert trace.trace_id == trace_id
        assert trace.spans
        assert len(trace.spans) > 0
        assert trace.service_name
        assert trace.start_time
        assert trace.duration_ms >= 0

    @pytest.mark.vcr
    async def test_get_trace_invalid_id(self, tempo_backend: TempoBackend) -> None:
        """Test that getting a trace with invalid ID raises an error."""
        invalid_trace_id = "00000000000000000000000000000000"

        with pytest.raises((ValueError, Exception)):
            await tempo_backend.get_trace(invalid_trace_id)


class TestTempoSearchSpans:
    """Test Tempo span search functionality."""

    @pytest.mark.vcr
    async def test_search_spans_basic(self, tempo_backend: TempoBackend) -> None:
        """Test basic span search."""
        query = SpanQuery(limit=20)

        spans = await tempo_backend.search_spans(query)

        assert isinstance(spans, list)
        # Each span should have required fields
        for span in spans:
            assert span.span_id
            assert span.trace_id
            assert span.operation_name
            assert span.service_name
            assert span.start_time
            assert span.duration_ms >= 0

    @pytest.mark.vcr
    async def test_search_spans_with_service_filter(self, tempo_backend: TempoBackend) -> None:
        """Test span search filtered by service name."""
        services = await tempo_backend.list_services()
        if len(services) == 0:
            pytest.skip("No services available for testing")

        service_name = services[0]
        query = SpanQuery(service_name=service_name, limit=20)

        spans = await tempo_backend.search_spans(query)

        # All spans should have the specified service name
        for span in spans:
            assert span.service_name == service_name

    @pytest.mark.vcr
    async def test_search_spans_with_limit(self, tempo_backend: TempoBackend) -> None:
        """Test span search with result limit."""
        query = SpanQuery(limit=10)

        spans = await tempo_backend.search_spans(query)

        assert len(spans) <= 10

    @pytest.mark.vcr
    async def test_search_spans_with_operation(self, tempo_backend: TempoBackend) -> None:
        """Test span search filtered by operation name."""
        services = await tempo_backend.list_services()
        if len(services) == 0:
            pytest.skip("No services available for testing")

        service_name = services[0]
        operations = await tempo_backend.get_service_operations(service_name)

        if len(operations) == 0:
            pytest.skip("No operations available for testing")

        operation_name = operations[0]
        query = SpanQuery(service_name=service_name, operation_name=operation_name, limit=20)

        spans = await tempo_backend.search_spans(query)

        # All spans should have the specified operation name
        for span in spans:
            assert span.operation_name == operation_name

    @pytest.mark.vcr
    async def test_search_spans_with_generic_filter(self, tempo_backend: TempoBackend) -> None:
        """Test span search with generic filter conditions."""
        # Filter for spans with duration > 10ms
        filter_condition = Filter(
            field="duration_ms", operator=FilterOperator.GT, value=10, value_type=FilterType.NUMBER
        )

        query = SpanQuery(filters=[filter_condition], limit=20)

        spans = await tempo_backend.search_spans(query)

        # All spans should meet the filter condition
        for span in spans:
            assert span.duration_ms > 10


class TestTempoLLMSpans:
    """Test Tempo with LLM-specific spans (if available)."""

    @pytest.mark.vcr
    async def test_search_llm_spans(self, tempo_backend: TempoBackend) -> None:
        """Test searching for LLM spans with gen_ai attributes."""
        # Filter for spans with gen_ai.system attribute
        filter_condition = Filter(
            field="gen_ai.system", operator=FilterOperator.EXISTS, value_type=FilterType.STRING
        )

        query = SpanQuery(filters=[filter_condition], limit=20)

        spans = await tempo_backend.search_spans(query)

        # All spans should be LLM spans
        for span in spans:
            assert span.is_llm_span
            assert span.attributes.gen_ai_system is not None

    @pytest.mark.vcr
    async def test_search_traces_with_llm_model_filter(self, tempo_backend: TempoBackend) -> None:
        """Test trace search with LLM model filter."""
        # Try common LLM models
        for model in ["gpt-4", "gpt-3.5-turbo", "claude-3", "claude-2"]:
            query = TraceQuery(gen_ai_request_model=model, limit=5)

            traces = await tempo_backend.search_traces(query)

            # If traces found, verify they match the model filter
            for trace in traces:
                llm_spans = [s for s in trace.spans if s.is_llm_span]
                if llm_spans:
                    # At least one LLM span should have the requested model
                    model_names = [
                        s.attributes.gen_ai_request_model for s in llm_spans if s.is_llm_span
                    ]
                    assert any(model in str(m) for m in model_names if m)


class TestTempoTraceQL:
    """Test Tempo-specific TraceQL functionality."""

    @pytest.mark.vcr
    async def test_search_with_contains_filter(self, tempo_backend: TempoBackend) -> None:
        """Test TraceQL CONTAINS operator (regex)."""
        services = await tempo_backend.list_services()
        if len(services) == 0:
            pytest.skip("No services available for testing")

        # Get a partial service name
        service_name = services[0]
        if len(service_name) < 3:
            pytest.skip("Service name too short for contains test")

        partial_name = service_name[:3]

        filter_condition = Filter(
            field="service.name",
            operator=FilterOperator.CONTAINS,
            value=partial_name,
            value_type=FilterType.STRING,
        )

        query = TraceQuery(filters=[filter_condition], limit=10)

        traces = await tempo_backend.search_traces(query)

        # All traces should have service name containing the partial name
        for trace in traces:
            assert partial_name in trace.service_name

    @pytest.mark.vcr
    async def test_search_with_in_filter(self, tempo_backend: TempoBackend) -> None:
        """Test TraceQL IN operator (OR logic)."""
        services = await tempo_backend.list_services()
        if len(services) < 2:
            pytest.skip("Need at least 2 services for IN operator test")

        # Get first two services
        service_names = services[:2]

        filter_condition = Filter(
            field="service.name",
            operator=FilterOperator.IN,
            values=service_names,
            value_type=FilterType.STRING,
        )

        query = TraceQuery(filters=[filter_condition], limit=10)

        traces = await tempo_backend.search_traces(query)

        # All traces should have service name in the list
        for trace in traces:
            assert trace.service_name in service_names

    @pytest.mark.vcr
    async def test_search_with_multiple_filters(self, tempo_backend: TempoBackend) -> None:
        """Test TraceQL with multiple filter conditions (AND logic)."""
        services = await tempo_backend.list_services()
        if len(services) == 0:
            pytest.skip("No services available for testing")

        service_name = services[0]

        # Combine service filter + duration filter
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

        traces = await tempo_backend.search_traces(query)

        # All traces should meet both conditions
        for trace in traces:
            assert trace.service_name == service_name
            assert trace.duration_ms > 50
