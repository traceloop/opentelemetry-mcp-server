"""Shared utility functions."""

from datetime import datetime


def parse_iso_timestamp(
    timestamp_str: str | None, param_name: str
) -> tuple[datetime | None, str | None]:
    """Parse ISO 8601 timestamp string.

    Args:
        timestamp_str: ISO 8601 timestamp string (e.g., "2024-01-01T00:00:00Z")
        param_name: Parameter name for error messages

    Returns:
        Tuple of (parsed datetime, error message or None)
    """
    if not timestamp_str:
        return None, None
    try:
        return datetime.fromisoformat(timestamp_str.replace("Z", "+00:00")), None
    except ValueError as e:
        return None, f"Invalid {param_name} format: {e}"
