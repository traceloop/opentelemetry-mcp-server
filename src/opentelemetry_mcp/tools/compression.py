import json
from typing import Any


def compact_json(data: Any, threshold: float = 0.05) -> Any:
    # recurse into dicts
    if isinstance(data, dict):
        return {k: compact_json(v, threshold) for k, v in data.items()}

    # compress uniform lists
    if isinstance(data, list) and len(data) > 1 and all(isinstance(item, dict) for item in data):
        first_keys = list(data[0].keys())
        if all(list(item.keys()) == first_keys for item in data):
            compressed = {"columns": first_keys, "rows": [list(item.values()) for item in data]}
            # only use if savings exceed threshold
            original_size = len(json.dumps(data))
            compressed_size = len(json.dumps(compressed))
            savings = (original_size - compressed_size) / original_size

            if savings >= threshold:
                return compressed

    # everything else passes through
    return data
