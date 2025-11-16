"""Integration tests for Jaeger backend using VCR recordings."""

import pytest

from opentelemetry_mcp.backends.jaeger import JaegerBackend
from opentelemetry_mcp.models import Filter, FilterOperator, FilterType, SpanQuery, TraceQuery

# Mark all tests in this module as integration and vcr
pytestmark = [pytest.mark.integration, pytest.mark.vcr]


class TestJaegerBackendHealth:
    """Test Jaeger backend health check."""

    @pytest.mark.vcr
    async def test_health_check_healthy(self, jaeger_backend: JaegerBackend) -> None:
        """Test health check against a healthy Jaeger instance."""
        health = await jaeger_backend.health_check()

        assert health.status == "healthy"
        assert health.backend == "jaeger"
        assert health.url is not None
        assert health.service_count is not None
        assert health.service_count >= 0


class TestJaegerListServices:
    """Test Jaeger service listing."""

    @pytest.mark.vcr
    async def test_list_services(self, jaeger_backend: JaegerBackend) -> None:
        """Test listing all services from Jaeger."""
        services = await jaeger_backend.list_services()

        assert isinstance(services, list)
        # Services should be strings
        for service in services:
            assert isinstance(service, str)
            assert len(service) > 0


class TestJaegerServiceOperations:
    """Test Jaeger service operations listing."""

    @pytest.mark.vcr
    async def test_get_service_operations(self, jaeger_backend: JaegerBackend) -> None:
        """Test getting operations for a specific service."""
        # First, get available services
        services = await jaeger_backend.list_services()
        assert len(services) > 0, "No services available for testing"

        # Get operations for the first service
        service_name = services[0]
        operations = await jaeger_backend.get_service_operations(service_name)

        assert isinstance(operations, list)
        # Operations should be strings
        for operation in operations:
            assert isinstance(operation, str)
            assert len(operation) > 0


class TestJaegerSearchTraces:
    """Test Jaeger trace search functionality."""

    @pytest.mark.vcr
    async def test_search_traces_basic(self, jaeger_backend: JaegerBackend) -> None:
        """Test basic trace search with service name."""
        # First, get available services
        services = await jaeger_backend.list_services()
        assert len(services) > 0, "No services available for testing"

        service_name = services[0]
        query = TraceQuery(service_name=service_name, limit=10)

        traces = await jaeger_backend.search_traces(query)

        assert isinstance(traces, list)
        # Each trace should have required fields
        for trace in traces:
            assert trace.trace_id
            assert trace.service_name == service_name
            assert trace.spans
            assert len(trace.spans) > 0
            assert trace.start_time
            assert trace.duration_ms >= 0

    @pytest.mark.vcr
    async def test_search_traces_without_service_name_fails(
        self, jaeger_backend: JaegerBackend
    ) -> None:
        """Test that Jaeger requires service_name parameter."""
        query = TraceQuery(limit=10)

        with pytest.raises(ValueError, match="requires 'service_name' parameter"):
            await jaeger_backend.search_traces(query)

    @pytest.mark.vcr
    async def test_search_traces_with_limit(self, jaeger_backend: JaegerBackend) -> None:
        """Test trace search with result limit."""
        services = await jaeger_backend.list_services()
        assert len(services) > 0

        service_name = services[0]
        query = TraceQuery(service_name=service_name, limit=5)

        traces = await jaeger_backend.search_traces(query)

        assert len(traces) <= 5

    @pytest.mark.vcr
    async def test_search_traces_with_operation(self, jaeger_backend: JaegerBackend) -> None:
        """Test trace search filtered by operation name."""
        services = await jaeger_backend.list_services()
        assert len(services) > 0

        service_name = services[0]

        # Get operations for this service
        operations = await jaeger_backend.get_service_operations(service_name)
        if len(operations) == 0:
            pytest.skip("No operations available for testing")

        operation_name = operations[0]
        query = TraceQuery(service_name=service_name, operation_name=operation_name, limit=10)

        traces = await jaeger_backend.search_traces(query)

        # All traces should have at least one span with the specified operation
        for trace in traces:
            operation_names = [span.operation_name for span in trace.spans]
            assert operation_name in operation_names

    @pytest.mark.vcr
    async def test_search_traces_with_duration_filter(self, jaeger_backend: JaegerBackend) -> None:
        """Test trace search with minimum duration filter."""
        services = await jaeger_backend.list_services()
        assert len(services) > 0

        service_name = services[0]
        min_duration_ms = 100  # 100ms minimum

        query = TraceQuery(service_name=service_name, min_duration_ms=min_duration_ms, limit=10)

        traces = await jaeger_backend.search_traces(query)

        # All traces should have duration >= min_duration_ms
        for trace in traces:
            assert trace.duration_ms >= min_duration_ms

    @pytest.mark.vcr
    async def test_search_traces_with_error_filter(self, jaeger_backend: JaegerBackend) -> None:
        """Test trace search filtered by error status."""
        services = await jaeger_backend.list_services()
        assert len(services) > 0

        service_name = services[0]
        query = TraceQuery(service_name=service_name, has_error=True, limit=10)

        traces = await jaeger_backend.search_traces(query)

        # All traces should have at least one span with error
        for trace in traces:
            assert any(span.has_error for span in trace.spans)

    @pytest.mark.vcr
    async def test_search_traces_with_generic_filter(self, jaeger_backend: JaegerBackend) -> None:
        """Test trace search with generic filter conditions."""
        services = await jaeger_backend.list_services()
        assert len(services) > 0

        service_name = services[0]

        # Filter for traces with duration > 50ms
        filter_condition = Filter(
            field="duration_ms", operator=FilterOperator.GT, value=50, value_type=FilterType.NUMBER
        )

        query = TraceQuery(service_name=service_name, filters=[filter_condition], limit=10)

        traces = await jaeger_backend.search_traces(query)

        # All traces should meet the filter condition
        for trace in traces:
            assert trace.duration_ms > 50


class TestJaegerGetTrace:
    """Test Jaeger get trace by ID functionality."""

    @pytest.mark.vcr
    async def test_get_trace_by_id(self, jaeger_backend: JaegerBackend) -> None:
        """Test retrieving a specific trace by ID."""
        # First, search for a trace to get a valid trace_id
        services = await jaeger_backend.list_services()
        assert len(services) > 0

        service_name = services[0]
        query = TraceQuery(service_name=service_name, limit=1)
        traces = await jaeger_backend.search_traces(query)

        assert len(traces) > 0, "No traces available for testing"
        trace_id = traces[0].trace_id

        # Now get the trace by ID
        trace = await jaeger_backend.get_trace(trace_id)

        assert trace.trace_id == trace_id
        assert trace.spans
        assert len(trace.spans) > 0
        assert trace.service_name
        assert trace.start_time
        assert trace.duration_ms >= 0

    @pytest.mark.vcr
    async def test_get_trace_invalid_id(self, jaeger_backend: JaegerBackend) -> None:
        """Test that getting a trace with invalid ID raises an error."""
        invalid_trace_id = "00000000000000000000000000000000"

        with pytest.raises((ValueError, Exception)):
            await jaeger_backend.get_trace(invalid_trace_id)


class TestJaegerSearchSpans:
    """Test Jaeger span search functionality."""

    @pytest.mark.vcr
    async def test_search_spans_basic(self, jaeger_backend: JaegerBackend) -> None:
        """Test basic span search with service name."""
        services = await jaeger_backend.list_services()
        assert len(services) > 0

        service_name = services[0]
        query = SpanQuery(service_name=service_name, limit=20)

        spans = await jaeger_backend.search_spans(query)

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
    async def test_search_spans_without_service_name_fails(
        self, jaeger_backend: JaegerBackend
    ) -> None:
        """Test that Jaeger requires service_name parameter for span search."""
        query = SpanQuery(limit=20)

        with pytest.raises(ValueError, match="requires 'service_name' parameter"):
            await jaeger_backend.search_spans(query)

    @pytest.mark.vcr
    async def test_search_spans_with_limit(self, jaeger_backend: JaegerBackend) -> None:
        """Test span search with result limit."""
        services = await jaeger_backend.list_services()
        assert len(services) > 0

        service_name = services[0]
        query = SpanQuery(service_name=service_name, limit=10)

        spans = await jaeger_backend.search_spans(query)

        assert len(spans) <= 10

    @pytest.mark.vcr
    async def test_search_spans_with_operation(self, jaeger_backend: JaegerBackend) -> None:
        """Test span search filtered by operation name."""
        services = await jaeger_backend.list_services()
        assert len(services) > 0

        service_name = services[0]
        operations = await jaeger_backend.get_service_operations(service_name)

        if len(operations) == 0:
            pytest.skip("No operations available for testing")

        operation_name = operations[0]
        query = SpanQuery(service_name=service_name, operation_name=operation_name, limit=20)

        spans = await jaeger_backend.search_spans(query)

        # All spans should have the specified operation name
        for span in spans:
            assert span.operation_name == operation_name

    @pytest.mark.vcr
    async def test_search_spans_with_generic_filter(self, jaeger_backend: JaegerBackend) -> None:
        """Test span search with generic filter conditions."""
        services = await jaeger_backend.list_services()
        assert len(services) > 0

        service_name = services[0]

        # Filter for spans with duration > 10ms
        filter_condition = Filter(
            field="duration_ms", operator=FilterOperator.GT, value=10, value_type=FilterType.NUMBER
        )

        query = SpanQuery(service_name=service_name, filters=[filter_condition], limit=20)

        spans = await jaeger_backend.search_spans(query)

        # All spans should meet the filter condition
        for span in spans:
            assert span.duration_ms > 10


class TestJaegerLLMSpans:
    """Test Jaeger with LLM-specific spans (if available)."""

    @pytest.mark.vcr
    async def test_search_llm_spans(self, jaeger_backend: JaegerBackend) -> None:
        """Test searching for LLM spans with gen_ai attributes."""
        services = await jaeger_backend.list_services()
        assert len(services) > 0

        service_name = services[0]

        # Filter for spans with gen_ai.system attribute
        filter_condition = Filter(
            field="gen_ai.system", operator=FilterOperator.EXISTS, value_type=FilterType.STRING
        )

        query = SpanQuery(service_name=service_name, filters=[filter_condition], limit=20)

        spans = await jaeger_backend.search_spans(query)

        # All spans should be LLM spans
        for span in spans:
            assert span.is_llm_span
            assert span.attributes.gen_ai_system is not None

    @pytest.mark.vcr
    async def test_search_traces_with_llm_model_filter(self, jaeger_backend: JaegerBackend) -> None:
        """Test trace search with LLM model filter."""
        services = await jaeger_backend.list_services()
        assert len(services) > 0

        service_name = services[0]

        # Try common LLM models
        for model in ["gpt-4", "gpt-3.5-turbo", "claude-3", "claude-2"]:
            query = TraceQuery(service_name=service_name, gen_ai_request_model=model, limit=5)

            traces = await jaeger_backend.search_traces(query)

            # If traces found, verify they match the model filter
            for trace in traces:
                llm_spans = [s for s in trace.spans if s.is_llm_span]
                if llm_spans:
                    # At least one LLM span should have the requested model
                    model_names = [
                        s.attributes.gen_ai_request_model for s in llm_spans if s.is_llm_span
                    ]
                    assert any(model in str(m) for m in model_names if m)
