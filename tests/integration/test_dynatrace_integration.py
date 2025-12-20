"""Integration tests for Dynatrace backend using VCR recordings."""

import pytest

from opentelemetry_mcp.backends.dynatrace import DynatraceBackend
from opentelemetry_mcp.models import SpanQuery, TraceQuery

# Mark all tests in this module as integration and vcr
pytestmark = [pytest.mark.integration, pytest.mark.vcr]


def _skip_if_placeholder_backend(backend: DynatraceBackend) -> None:
    """Skip tests when no real Dynatrace URL is configured."""
    if "abc12345.live.dynatrace.com" in getattr(backend, "url", ""):
        pytest.skip("DYNATRACE_URL not configured; skipping Dynatrace integration tests")


class TestDynatraceBackendHealth:
    """Test Dynatrace backend health check."""

    @pytest.mark.vcr
    async def test_health_check_healthy(self, dynatrace_backend: DynatraceBackend) -> None:
        """Test health check against a Dynatrace instance."""
        _skip_if_placeholder_backend(dynatrace_backend)
        health = await dynatrace_backend.health_check()

        assert health.status in ("healthy", "unhealthy")
        assert health.backend == "dynatrace"
        assert health.url is not None


class TestDynatraceListServices:
    """Test Dynatrace service listing."""

    @pytest.mark.vcr
    async def test_list_services(self, dynatrace_backend: DynatraceBackend) -> None:
        """Test listing all services from Dynatrace."""
        _skip_if_placeholder_backend(dynatrace_backend)
        services = await dynatrace_backend.list_services()

        assert isinstance(services, list)
        for service in services:
            assert isinstance(service, str)
            assert len(service) > 0


class TestDynatraceServiceOperations:
    """Test Dynatrace service operations listing."""

    @pytest.mark.vcr
    async def test_get_service_operations(self, dynatrace_backend: DynatraceBackend) -> None:
        """Test getting operations for a specific service."""
        _skip_if_placeholder_backend(dynatrace_backend)
        services = await dynatrace_backend.list_services()
        assert len(services) > 0, "No services available for testing"

        service_name = services[0]
        operations = await dynatrace_backend.get_service_operations(service_name)

        assert isinstance(operations, list)
        for op in operations:
            assert isinstance(op, str)
            assert len(op) > 0


class TestDynatraceSearchTraces:
    """Test Dynatrace trace search functionality."""

    @pytest.mark.vcr
    async def test_search_traces_basic(self, dynatrace_backend: DynatraceBackend) -> None:
        """Test basic trace search with service name."""
        _skip_if_placeholder_backend(dynatrace_backend)
        services = await dynatrace_backend.list_services()
        assert len(services) > 0, "No services available for testing"

        service_name = services[0]
        query = TraceQuery(service_name=service_name, limit=10)

        traces = await dynatrace_backend.search_traces(query)

        assert isinstance(traces, list)
        for trace in traces:
            assert trace.trace_id
            assert trace.service_name == service_name
            assert trace.spans
            assert len(trace.spans) > 0
            assert trace.start_time
            assert trace.duration_ms >= 0

    @pytest.mark.vcr
    async def test_get_trace_by_id(self, dynatrace_backend: DynatraceBackend) -> None:
        """Test retrieving a specific trace by ID."""
        _skip_if_placeholder_backend(dynatrace_backend)
        services = await dynatrace_backend.list_services()
        assert len(services) > 0

        service_name = services[0]
        traces = await dynatrace_backend.search_traces(TraceQuery(service_name=service_name, limit=1))

        assert len(traces) > 0, "No traces available for testing"
        trace_id = traces[0].trace_id

        trace = await dynatrace_backend.get_trace(trace_id)

        assert trace.trace_id == trace_id
        assert trace.spans
        assert len(trace.spans) > 0
        assert trace.service_name
        assert trace.start_time
        assert trace.duration_ms >= 0


class TestDynatraceSearchSpans:
    """Test Dynatrace span search functionality."""

    @pytest.mark.vcr
    async def test_search_spans_basic(self, dynatrace_backend: DynatraceBackend) -> None:
        """Test basic span search with service name."""
        _skip_if_placeholder_backend(dynatrace_backend)
        services = await dynatrace_backend.list_services()
        assert len(services) > 0

        service_name = services[0]
        query = SpanQuery(service_name=service_name, limit=20)

        spans = await dynatrace_backend.search_spans(query)

        assert isinstance(spans, list)
        for span in spans:
            assert span.span_id
            assert span.trace_id
            assert span.operation_name
            assert span.service_name
            assert span.start_time
            assert span.duration_ms >= 0
