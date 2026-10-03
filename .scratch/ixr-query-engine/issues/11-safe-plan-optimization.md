# 11: Optimize plans without changing results

**What to build:** Callers benefit from conservative plan simplification while query results, operation order, and errors remain unchanged.

**Blocked by:** 07 (Sort query results in Python), 08 (Group and aggregate in Python)

**Status:** resolved

**Parent specification:** IXR and query execution specification (local tracker, same feature).

**Scope:** Python tooling only; preserve core logging and existing CLI/MCP inputs.

- [x] Adjacent pure filters/limits and boolean composition normalize safely; dependency analysis preserves fields required for execution and output.
- [x] Filters never move across limits. Projection rewrites require valid lineage; transformations preserve missing/null semantics and observable error behavior.
- [x] Static explanation exposes meaningful logical normalization without reading sources or promising backend-specific speedups.
- [x] Caller tests compare rewritten/unrewritten results and errors over finite records, closed/open schemas, sorting, grouping, and operation-order edge cases.
- [x] Native physical optimization remains adapter-owned; documentation separates supported logical rewrites from deferred advanced pushdown.

## Resolution

Added backend-aware normalization after original validation. Python combines pure
builtin filters and adjacent limits; both adapters collapse lineage-validated
adjacent projections and simplify boolean structure without erasing dependencies.
Polars retains staged filters and narrowing positive batched limits to preserve
binding errors and read-ahead metadata. Original operation indices survive merges;
static explanation reports rewrites and origins without reading sources.
Custom predicates, filter/limit order and blocking error behavior remain unchanged.
Focused implementation documentation records supported/deferred rewrites.

Validation: 387 tests passed on Python 3.13 with actual Polars 1.29.0; Ruff, Pyrefly
and diff whitespace checks passed. Coordinator owns final Python 3.10 checks and
validation against the current Polars version.
