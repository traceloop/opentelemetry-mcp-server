"""Client-side filter engine for post-query filtering of traces."""

import logging
from typing import Any

from opentelemetry_mcp.models import Filter, FilterOperator, FilterType, TraceData

logger = logging.getLogger(__name__)


class FilterEngine:
    """Client-side filter engine for applying filters to traces."""

    @staticmethod
    def apply_filters(traces: list[TraceData], filters: list[Filter]) -> list[TraceData]:
        """Apply all filters to traces and return matching traces.

        Args:
            traces: List of traces to filter
            filters: List of Filter conditions (combined with AND logic)

        Returns:
            Filtered list of traces matching all conditions
        """
        if not filters:
            return traces

        filtered_traces = []
        for trace in traces:
            if FilterEngine._matches_all_filters(trace, filters):
                filtered_traces.append(trace)

        logger.debug(
            f"Client-side filtering: {len(traces)} traces -> {len(filtered_traces)} after applying {len(filters)} filters"
        )
        return filtered_traces

    @staticmethod
    def _matches_all_filters(trace: TraceData, filters: list[Filter]) -> bool:
        """Check if a trace matches all filters (AND logic).

        Args:
            trace: Trace to check
            filters: List of filters to apply

        Returns:
            True if trace matches all filters
        """
        for filter_obj in filters:
            if not FilterEngine._matches_filter(trace, filter_obj):
                return False
        return True

    @staticmethod
    def _matches_filter(trace: TraceData, filter_obj: Filter) -> bool:
        """Check if a trace matches a single filter.

        Args:
            trace: Trace to check
            filter_obj: Filter to apply

        Returns:
            True if trace matches the filter
        """
        field = filter_obj.field
        operator = filter_obj.operator

        # Get values from trace (may check multiple spans)
        values = FilterEngine._get_field_values(trace, field)

        # Handle existence operators
        if operator == FilterOperator.EXISTS:
            return len(values) > 0
        if operator == FilterOperator.NOT_EXISTS:
            return len(values) == 0

        # For other operators, check if ANY span matches (OR logic across spans)
        for value in values:
            if FilterEngine._compare_value(value, filter_obj):
                return True

        return False

    @staticmethod
    def _get_field_values(trace: TraceData, field: str) -> list[Any]:
        """Extract values for a field from trace and its spans.

        Supports both trace-level fields (duration, status, etc.) and
        span-level fields (gen_ai.system, span attributes, etc.).

        Args:
            trace: Trace to extract from
            field: Field name in dotted notation

        Returns:
            List of values found (may be empty, or contain multiple values from different spans)
        """
        values: list[Any] = []

        # Check trace-level fields first
        if field == "trace_id":
            values.append(trace.trace_id)
        elif field == "service.name":
            values.append(trace.service_name)
        elif field == "name" or field == "operation_name":
            values.append(trace.root_operation)
        elif field == "duration":
            values.append(trace.duration_ms)
        elif field == "status":
            values.append(trace.status)
        elif field == "span_count":
            values.append(len(trace.spans))
        elif field == "llm_span_count":
            values.append(len(trace.llm_spans))
        elif field == "total_tokens":
            values.append(trace.total_llm_tokens)
        elif field == "has_errors":
            values.append(trace.has_errors)
        else:
            # Check span-level attributes (collect from all spans)
            for span in trace.spans:
                span_values = FilterEngine._get_span_field_values(span, field)
                values.extend(span_values)

        return [v for v in values if v is not None]

    @staticmethod
    def _get_span_field_values(span: Any, field: str) -> list[Any]:
        """Extract values for a field from a span.

        Args:
            span: SpanData object
            field: Field name in dotted notation

        Returns:
            List of values found in this span
        """
        values: list[Any] = []

        # Check span-level fields
        if field == "span_id":
            values.append(span.span_id)
        elif field == "parent_span_id":
            if span.parent_span_id:
                values.append(span.parent_span_id)
        elif field == "service.name":
            values.append(span.service_name)
        elif field == "name" or field == "operation_name":
            values.append(span.operation_name)
        elif field == "duration":
            values.append(span.duration_ms)
        elif field == "status":
            values.append(span.status)
        else:
            # Check span attributes using dotted notation
            attr_value = span.attributes.get(field)
            if attr_value is not None:
                values.append(attr_value)

        return [v for v in values if v is not None]

    @staticmethod
    def _compare_value(actual: Any, filter_obj: Filter) -> bool:
        """Compare an actual value against a filter condition.

        Args:
            actual: Actual value from trace/span
            filter_obj: Filter with operator and expected value(s)

        Returns:
            True if actual value matches the filter condition
        """
        operator = filter_obj.operator
        expected = filter_obj.value
        expected_values = filter_obj.values

        # Convert to appropriate type
        try:
            if filter_obj.value_type == FilterType.NUMBER:
                actual_num = float(actual)
                expected_num = float(expected) if expected is not None else None
                expected_values_num = (
                    [float(v) for v in expected_values] if expected_values is not None else None
                )

                # Apply numeric operators
                if operator == FilterOperator.EQUALS:
                    return actual_num == expected_num
                elif operator == FilterOperator.NOT_EQUALS:
                    return actual_num != expected_num
                elif operator == FilterOperator.GT:
                    return actual_num > expected_num if expected_num is not None else False
                elif operator == FilterOperator.LT:
                    return actual_num < expected_num if expected_num is not None else False
                elif operator == FilterOperator.GTE:
                    return actual_num >= expected_num if expected_num is not None else False
                elif operator == FilterOperator.LTE:
                    return actual_num <= expected_num if expected_num is not None else False
                elif operator == FilterOperator.IN:
                    return actual_num in (expected_values_num or [])
                elif operator == FilterOperator.NOT_IN:
                    return actual_num not in (expected_values_num or [])
                elif operator == FilterOperator.BETWEEN:
                    if expected_values_num and len(expected_values_num) == 2:
                        return expected_values_num[0] <= actual_num <= expected_values_num[1]
                    return False

            elif filter_obj.value_type == FilterType.BOOLEAN:
                actual_bool = bool(actual)
                expected_bool = bool(expected) if expected is not None else None

                if operator == FilterOperator.EQUALS:
                    return actual_bool == expected_bool
                elif operator == FilterOperator.NOT_EQUALS:
                    return actual_bool != expected_bool

            else:  # STRING
                actual_str = str(actual)
                expected_str = str(expected) if expected is not None else ""
                expected_values_str = (
                    [str(v) for v in expected_values] if expected_values is not None else None
                )

                # String operators
                if operator == FilterOperator.EQUALS:
                    return actual_str == expected_str
                elif operator == FilterOperator.NOT_EQUALS:
                    return actual_str != expected_str
                elif operator == FilterOperator.CONTAINS:
                    return expected_str in actual_str
                elif operator == FilterOperator.NOT_CONTAINS:
                    return expected_str not in actual_str
                elif operator == FilterOperator.STARTS_WITH:
                    return actual_str.startswith(expected_str)
                elif operator == FilterOperator.ENDS_WITH:
                    return actual_str.endswith(expected_str)
                elif operator == FilterOperator.IN:
                    return actual_str in (expected_values_str or [])
                elif operator == FilterOperator.NOT_IN:
                    return actual_str not in (expected_values_str or [])

        except (ValueError, TypeError):
            logger.warning(f"Type conversion failed for value: {actual}")
            return False

        logger.warning(f"Unknown operator: {operator}")
        return False
