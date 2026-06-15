# Contribution README

## Reproduction Process

### Environment Setup

- Cloned the repo and ran `uv sync` to install dependencies
- Had to install `uv` first since it wasn't available globally (`curl -LsSf https://astral.sh/uv/install.sh | sh`)
- Python version pinned to 3.13.1 via `.python-version` — uv handled this automatically
- All commands must be prefixed with `uv run` (e.g. `uv run pytest`, `uv run mypy src/`)
- Resolved 9 ruff import ordering errors across tool files using `uv run ruff check --fix .`
- Fixed mypy errors caused by inconsistent attribute names (`config.compression` vs `config.compress_responses`) across tool files

### Steps to Reproduce

1. Clone the repository: `git clone https://github.com/traceloop/opentelemetry-mcp-server.git`
2. Install dependencies: `uv sync`
3. Query any tool (e.g. `list_llm_models`) with multiple results
4. Observe the JSON response — every object in the array repeats the same field names (`model`, `provider`, `count`, etc.) for every row
5. For a response with 100 traces, field names are duplicated 100 times — wasting 30-60% of tokens on every AI agent call

### Branch Link

https://github.com/Suhasrv2403/opentelemetry-mcp-server/tree/feat/tool-response-compression

## Solution Approach

### Implementation Plan

- **Understand**: Tool responses return arrays of uniform objects where field names repeat on every row, wasting tokens in AI agent workflows
- **Match**: This maps to a classic data compression pattern — convert repeated key-value pairs into a column/row tabular format
- **Plan**:
  - Create `src/opentelemetry_mcp/tools/compression.py` with `compact_json()` — a recursive utility that converts uniform arrays of dicts into `{"columns": [...], "rows": [...]}` format
  - Add `compress_responses: bool = True` to `ServerConfig` in `config.py`, reading from `COMPRESS_RESPONSES` env var
  - Hook `compact_json()` into 8 high-impact tool files before the final `json.dumps()` call
  - Write unit tests in `tests/test_compression.py` covering: basic compression, pass-through edge cases (empty, single item, non-uniform keys), nested structures, threshold behavior, and losslessness
  - Document the config option in `.env.example`
- **Implement**: Only compress when savings exceed 5% threshold to avoid overhead on small responses
- **Review**: All four checks must pass — `ruff format`, `ruff check`, `mypy`, `pytest`
- **Evaluate**: 17 new unit tests added, all passing. 92 total tests pass, 2 skipped (pre-existing)