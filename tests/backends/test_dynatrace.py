"""Unit tests for Dynatrace backend implementation."""

import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from opentelemetry_mcp.backends.dynatrace import DynatraceBackend
from opentelemetry_mcp.models import Filter, FilterOperator, FilterType, SpanQuery, TraceQuery


class TestDynatraceBackend:
    """Test Dynatrace backend implementation."""

    @pytest.fixture
    def backend(self) -> DynatraceBackend:
        """Create a Dynatrace backend instance for testing."""
        return DynatraceBackend(
            url="https://abc12345.live.dynatrace.com",
            api_key="dt0c01.ABC123",
            timeout=30.0,
        )

    def test_create_headers(self, backend: DynatraceBackend) -> None:
        """Test header creation with API key."""
        headers = backend._create_headers()
        assert "Authorization" in headers
        assert headers["Authorization"] == "Api-Token dt0c01.ABC123"
        assert headers["Content-Type"] == "application/json"

    def test_create_headers_no_api_key(self) -> None:
        """Test header creation without API key."""
        backend = DynatraceBackend(url="https://abc12345.live.dynatrace.com")
        headers = backend._create_headers()
        assert "Authorization" not in headers
        assert headers["Content-Type"] == "application/json"

    def test_get_supported_operators(self, backend: DynatraceBackend) -> None:
        """Test supported operators."""
        operators = backend.get_supported_operators()
        assert FilterOperator.EQUALS in operators

    @pytest.mark.asyncio
    async def test_search_traces_basic(self, backend: DynatraceBackend) -> None:
        """Test basic trace search."""
        # Mock trace search response
        mock_traces_response = {
            "traces": [
                {"traceId": "trace1", "serviceName": "test-service"},
                {"traceId": "trace2", "serviceName": "test-service"},
            ]
        }

        # Mock get_trace responses
        mock_trace1 = {
            "spans": [
                {
                    "spanId": "span1",
                    "operationName": "test_op",
                    "startTime": int((datetime.now() - timedelta(minutes=5)).timestamp() * 1000),
                    "duration": 1000,
                    "serviceName": "test-service",
                    "attributes": {},
                }
            ]
        }

        with patch.object(backend.client, "get") as mock_get:
            # First call: search_traces
            mock_response1 = MagicMock()
            mock_response1.json.return_value = mock_traces_response
            mock_response1.raise_for_status = MagicMock()

            # Second and third calls: get_trace for each trace
            mock_response2 = MagicMock()
            mock_response2.json.return_value = mock_trace1
            mock_response2.raise_for_status = MagicMock()

            mock_get.side_effect = [mock_response1, mock_response2, mock_response2]

            query = TraceQuery(service_name="test-service", limit=10)
            traces = await backend.search_traces(query)

            assert len(traces) > 0
            assert all(trace.service_name == "test-service" for trace in traces)

    @pytest.mark.asyncio
    async def test_get_trace(self, backend: DynatraceBackend) -> None:
        """Test getting a specific trace by ID."""
        trace_id = "test-trace-id"
        mock_trace_data = {
            "spans": [
                {
                    "spanId": "span1",
                    "operationName": "test_op",
                    "startTime": int(datetime.now().timestamp() * 1000),
                    "duration": 1000,
                    "serviceName": "test-service",
                    "attributes": {},
                }
            ]
        }

        with patch.object(backend.client, "get") as mock_get:
            mock_response = MagicMock()
            mock_response.json.return_value = mock_trace_data
            mock_response.raise_for_status = MagicMock()
            mock_get.return_value = mock_response

            trace = await backend.get_trace(trace_id)

            assert trace.trace_id == trace_id
            assert len(trace.spans) > 0
            assert trace.service_name == "test-service"

    @pytest.mark.asyncio
    async def test_list_services(self, backend: DynatraceBackend) -> None:
        """Test listing services."""
        # First try services endpoint
        mock_services_response = {
            "services": [
                {"name": "service1"},
                {"name": "service2"},
            ]
        }

        with patch.object(backend.client, "get") as mock_get:
            mock_response = MagicMock()
            mock_response.json.return_value = mock_services_response
            mock_response.raise_for_status = MagicMock()
            mock_get.return_value = mock_response

            services = await backend.list_services()

            assert len(services) > 0
            assert "service1" in services
            assert "service2" in services

    @pytest.mark.asyncio
    async def test_list_services_fallback(self, backend: DynatraceBackend) -> None:
        """Test listing services with fallback to trace search."""
        # First call fails (services endpoint not available)
        # Second call succeeds (trace search)
        mock_traces_response = {
            "traces": [
                {"traceId": "trace1", "serviceName": "service1"},
                {"traceId": "trace2", "serviceName": "service2"},
            ]
        }

        with patch.object(backend.client, "get") as mock_get:
            # First call fails
            mock_response1 = MagicMock()
            mock_response1.raise_for_status.side_effect = Exception("Not found")

            # Second call succeeds
            mock_response2 = MagicMock()
            mock_response2.json.return_value = mock_traces_response
            mock_response2.raise_for_status = MagicMock()

            mock_get.side_effect = [mock_response1, mock_response2]

            services = await backend.list_services()

            assert len(services) > 0
            assert "service1" in services
            assert "service2" in services

    @pytest.mark.asyncio
    async def test_get_service_operations(self, backend: DynatraceBackend) -> None:
        """Test getting operations for a service."""
        mock_traces_response = {
            "traces": [
                {"traceId": "trace1", "operationName": "op1"},
                {"traceId": "trace2", "operationName": "op2"},
            ]
        }

        with patch.object(backend.client, "get") as mock_get:
            mock_response = MagicMock()
            mock_response.json.return_value = mock_traces_response
            mock_response.raise_for_status = MagicMock()
            mock_get.return_value = mock_response

            operations = await backend.get_service_operations("test-service")

            assert len(operations) > 0
            assert "op1" in operations
            assert "op2" in operations

    @pytest.mark.asyncio
    async def test_search_spans(self, backend: DynatraceBackend) -> None:
        """Test searching for spans."""
        # Mock trace search response
        mock_traces_response = {
            "traces": [
                {"traceId": "trace1", "serviceName": "test-service"},
            ]
        }

        # Mock get_trace response
        mock_trace = {
            "spans": [
                {
                    "spanId": "span1",
                    "operationName": "test_op",
                    "startTime": int(datetime.now().timestamp() * 1000),
                    "duration": 1000,
                    "serviceName": "test-service",
                    "attributes": {},
                }
            ]
        }

        with patch.object(backend.client, "get") as mock_get:
            mock_response1 = MagicMock()
            mock_response1.json.return_value = mock_traces_response
            mock_response1.raise_for_status = MagicMock()

            mock_response2 = MagicMock()
            mock_response2.json.return_value = mock_trace
            mock_response2.raise_for_status = MagicMock()

            mock_get.side_effect = [mock_response1, mock_response2]

            query = SpanQuery(service_name="test-service", limit=10)
            spans = await backend.search_spans(query)

            assert len(spans) > 0
            assert all(span.service_name == "test-service" for span in spans)

    @pytest.mark.asyncio
    async def test_health_check_healthy(self, backend: DynatraceBackend) -> None:
        """Test health check when backend is healthy."""
        mock_services_response = {"services": [{"name": "service1"}]}

        with patch.object(backend.client, "get") as mock_get:
            mock_response = MagicMock()
            mock_response.json.return_value = mock_services_response
            mock_response.raise_for_status = MagicMock()
            mock_get.return_value = mock_response

            health = await backend.health_check()

            assert health.status == "healthy"
            assert health.backend == "dynatrace"
            assert health.service_count == 1

    @pytest.mark.asyncio
    async def test_health_check_unhealthy(self, backend: DynatraceBackend) -> None:
        """Test health check when backend is unhealthy."""
        with patch.object(backend.client, "get") as mock_get:
            mock_get.side_effect = Exception("Connection failed")

            health = await backend.health_check()

            assert health.status == "unhealthy"
            assert health.backend == "dynatrace"
            assert health.error is not None

    def test_parse_dynatrace_span(self, backend: DynatraceBackend) -> None:
        """Test parsing Dynatrace span data."""
        trace_id = "test-trace"
        span_data = {
            "spanId": "span1",
            "operationName": "test_op",
            "startTime": int(datetime.now().timestamp() * 1000),
            "duration": 1000,
            "serviceName": "test-service",
            "attributes": {
                "gen_ai.system": "openai",
                "gen_ai.request.model": "gpt-4",
            },
        }

        span = backend._parse_dynatrace_span(span_data, trace_id)

        assert span is not None
        assert span.span_id == "span1"
        assert span.operation_name == "test_op"
        assert span.service_name == "test-service"
        assert span.trace_id == trace_id
        assert span.attributes.gen_ai_system == "openai"

    def test_parse_dynatrace_trace(self, backend: DynatraceBackend) -> None:
        """Test parsing Dynatrace trace data."""
        trace_id = "test-trace"
        trace_data = {
            "spans": [
                {
                    "spanId": "span1",
                    "operationName": "test_op",
                    "startTime": int(datetime.now().timestamp() * 1000),
                    "duration": 1000,
                    "serviceName": "test-service",
                    "attributes": {},
                }
            ]
        }

        trace = backend._parse_dynatrace_trace(trace_data, trace_id)

        assert trace is not None
        assert trace.trace_id == trace_id
        assert len(trace.spans) == 1
        assert trace.service_name == "test-service"

