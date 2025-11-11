"""Client-side filter engine for post-query filtering of traces and spans."""

import logging
from typing import Any, TypeVar, overload

from opentelemetry_mcp.models import Filter, FilterOperator, FilterType, SpanData, TraceData

logger = logging.getLogger(__name__)

T = TypeVar("T", TraceData, SpanData)


class FilterEngine:
    """Client-side filter engine for applying filters to traces and spans."""

    @overload
    @staticmethod
    def apply_filters(items: list[TraceData], filters: list[Filter]) -> list[TraceData]: ...

    @overload
    @staticmethod
    def apply_filters(items: list[SpanData], filters: list[Filter]) -> list[SpanData]: ...

    @staticmethod
    def apply_filters(
        items: list[TraceData] | list[SpanData], filters: list[Filter]
    ) -> list[TraceData] | list[SpanData]:
        """Apply all filters to traces or spans and return matching items.

        Args:
            items: List of traces or spans to filter
            filters: List of Filter conditions (combined with AND logic)

        Returns:
            Filtered list of items matching all conditions
        """
        if not filters:
            return items

        filtered_items: list[TraceData] | list[SpanData]
        if isinstance(items[0] if items else None, TraceData):
            filtered_items = []
            for item in items:
                if FilterEngine._matches_all_filters(item, filters):
                    filtered_items.append(item)  # type: ignore[arg-type]
        else:
            filtered_items = []
            for item in items:
                if FilterEngine._matches_all_filters(item, filters):
                    filtered_items.append(item)  # type: ignore[arg-type]

        logger.debug(
            f"Client-side filtering: {len(items)} items -> {len(filtered_items)} after applying {len(filters)} filters"
        )
        return filtered_items

    @staticmethod
    def _matches_all_filters(item: TraceData | SpanData, filters: list[Filter]) -> bool:
        """Check if an item (trace or span) matches all filters (AND logic).

        Args:
            item: Trace or span to check
            filters: List of filters to apply

        Returns:
            True if item matches all filters
        """
        for filter_obj in filters:
            if not FilterEngine._matches_filter(item, filter_obj):
                return False
        return True

    @staticmethod
    def _matches_filter(item: TraceData | SpanData, filter_obj: Filter) -> bool:
        """Check if an item (trace or span) matches a single filter.

        Args:
            item: Trace or span to check
            filter_obj: Filter to apply

        Returns:
            True if item matches the filter
        """
        field = filter_obj.field
        operator = filter_obj.operator

        # Get values from item (may check multiple spans for traces, single span for spans)
        values = FilterEngine._get_field_values(item, field)

        # Handle existence operators
        if operator == FilterOperator.EXISTS:
            return len(values) > 0
        if operator == FilterOperator.NOT_EXISTS:
            return len(values) == 0

        # Handle empty values
        if not values:
            return False

        # For negative operators (NOT_EQUALS, NOT_IN, NOT_CONTAINS), require ALL values to satisfy the predicate
        # For positive operators, check if ANY value matches (OR logic across spans)
        negative_ops = {
            FilterOperator.NOT_EQUALS,
            FilterOperator.NOT_CONTAINS,
            FilterOperator.NOT_IN,
        }

        if operator in negative_ops:
            return all(FilterEngine._compare_value(value, filter_obj) for value in values)

        return any(FilterEngine._compare_value(value, filter_obj) for value in values)

    @staticmethod
    def _get_field_values(item: TraceData | SpanData, field: str) -> list[Any]:
        """Extract values for a field from trace/span.

        For TraceData: Supports both trace-level fields and span-level fields (checks all spans).
        For SpanData: Extracts field directly from the span.

        Args:
            item: Trace or span to extract from
            field: Field name in dotted notation

        Returns:
            List of values found (may be empty, or contain multiple values from trace spans)
        """
        values: list[Any] = []

        # Handle SpanData
        if isinstance(item, SpanData):
            span_values = FilterEngine._get_span_field_values(item, field)
            return [v for v in span_values if v is not None]

        # Handle TraceData
        trace = item

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
