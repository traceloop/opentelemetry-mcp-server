import json
from typing import Any


def compact_json(data: Any, threshold: float = 0.05) -> Any:
    # recurse into dicts
    if isinstance(data, dict):
        return {k: compact_json(v, threshold) for k, v in data.items()}

    # compress uniform lists
    if isinstance(data, dict):
        return {k: compact_json(v, threshold) for k, v in data.items()}

    # recurse into lists, then compress uniform lists of dicts
    if isinstance(data, list):
        compacted_items = [compact_json(item, threshold) for item in data]
        if len(compacted_items) > 1 and all(isinstance(item, dict) for item in compacted_items):
            first_keys = list(compacted_items[0].keys())
            if all(list(item.keys()) == first_keys for item in compacted_items):
                compressed = {
                    "columns": first_keys,
                    "rows": [[item[key] for key in first_keys] for item in compacted_items],
                }
                # only use if savings exceed threshold
                original_size = len(json.dumps(compacted_items))
                compressed_size = len(json.dumps(compressed))
                savings = (original_size - compressed_size) / original_size

                if savings >= threshold:
                    return compressed
        return compacted_items

    # everything else passes through
    return data
