# Contribution README

## Reproduction Process

### Steps to Reproduce

1. Clone the repository: `git clone https://github.com/traceloop/opentelemetry-mcp-server.git`
2. Install dependencies: `uv sync`
3. Query any tool (e.g. `list_llm_models`) with multiple results
4. Observe the JSON response — every object in the array repeats the same field names (`model`, `provider`, `count`, etc.) for every row
5. Count the characters — field names are duplicated N times for N rows, wasting tokens on every AI agent call

### Reproduction Evidence

Branch: https://github.com/Suhasrv2403/opentelemetry-mcp-server/tree/feat/tool-response-compression

## Implementation Plan

- Create `src/opentelemetry_mcp/tools/compression.py` with a `compact_json()` utility function that converts uniform arrays of dicts into a column/row tabular format
- Add `compress_responses: bool = True` to `ServerConfig` in `config.py`, reading from `COMPRESS_RESPONSES` env var
- Hook `compact_json()` into all 8 high-impact tool files before the final `json.dumps()` call
- Write unit tests in `tests/test_compression.py` covering compression, pass-through edge cases, nested structures, and losslessness
- Document the config option in `.env.example` and `README.md
