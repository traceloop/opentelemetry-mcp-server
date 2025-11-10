"""Abstract base backend for OpenTelemetry trace storage systems."""

from abc import ABC, abstractmethod
from typing import Any

import httpx

from opentelemetry_mcp.attributes import HealthCheckResponse
from opentelemetry_mcp.models import FilterOperator, TraceData, TraceQuery


class BaseBackend(ABC):
    """Abstract interface for OpenTelemetry trace backends."""

    def __init__(self, url: str, api_key: str | None = None, timeout: float = 30.0):
        """Initialize backend with connection parameters.

        Args:
            url: Backend API URL
            api_key: Optional API key for authentication
            timeout: Request timeout in seconds
        """
        self.url = url
        self.api_key = api_key
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None

    @property
    def client(self) -> httpx.AsyncClient:
        """Get or create HTTP client with connection pooling.

        Returns:
            Reusable AsyncClient instance with automatic connection pooling
        """
        # Check if client needs to be created/recreated
        # Use try-except because .is_closed can fail if event loop is closed
        needs_new_client = False
        if self._client is None:
            needs_new_client = True
        else:
            try:
                if self._client.is_closed:
                    needs_new_client = True
            except RuntimeError:
                # Event loop is closed, need new client
                needs_new_client = True

        if needs_new_client:
            self._client = httpx.AsyncClient(
                base_url=self.url,
                headers=self._create_headers(),
                timeout=self.timeout,
                follow_redirects=True,
            )

        # Type check: ensure client is never None
        assert self._client is not None, "Client should be initialized by now"
        return self._client

    @abstractmethod
    def _create_headers(self) -> dict[str, str]:
        """Create backend-specific HTTP headers.

        Returns:
            Dictionary of HTTP headers (e.g., Authorization, Content-Type)
        """
        pass

    @abstractmethod
    def get_supported_operators(self) -> set[FilterOperator]:
        """Get the set of filter operators that this backend natively supports.

        Operators not in this set will be applied via client-side filtering.

        Returns:
            Set of natively supported FilterOperator values
        """
        pass

    @abstractmethod
    async def search_traces(self, query: TraceQuery) -> list[TraceData]:
        """Search for traces matching the given query.

        Args:
            query: Trace query parameters

        Returns:
            List of matching traces with all spans

        Raises:
            Exception: If the backend query fails
        """
        pass

    @abstractmethod
    async def get_trace(self, trace_id: str) -> TraceData:
        """Get a specific trace by ID.

        Args:
            trace_id: Trace identifier

        Returns:
            Complete trace data with all spans

        Raises:
            Exception: If trace not found or query fails
        """
        pass

    @abstractmethod
    async def list_services(self) -> list[str]:
        """List all available services.

        Returns:
            List of service names

        Raises:
            Exception: If query fails
        """
        pass

    @abstractmethod
    async def get_service_operations(self, service_name: str) -> list[str]:
        """Get all operations for a specific service.

        Args:
            service_name: Service name

        Returns:
            List of operation names

        Raises:
            Exception: If query fails
        """
        pass

    @abstractmethod
    async def health_check(self) -> HealthCheckResponse:
        """Check backend health and connectivity.

        Returns:
            Health status information

        Raises:
            Exception: If backend is unreachable
        """
        pass

    async def __aenter__(self) -> "BaseBackend":
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Async context manager exit."""
        await self.close()

    async def close(self) -> None:
        """Close HTTP client connections."""
        if self._client:
            await self._client.aclose()
            self._client = None
