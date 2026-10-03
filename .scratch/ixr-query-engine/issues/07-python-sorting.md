# 07: Sort query results in Python

**What to build:** Callers sort finite record-query results globally, with stable ties and explicit placement of missing/null values.

**Blocked by:** 02 (Execute basic query plans in Python)

**Status:** resolved

**Parent specification:** IXR and query execution specification (local tracker, same feature).

**Scope:** Python tooling only; preserve core logging and existing CLI/MCP inputs.

- [x] sort_by supports one literal field, direction, and specified missing/null placement; sort dependencies are validated against the current output schema.
- [x] Record ties use stable source ordinals. Compatible numbers or strings are ordered; incompatible present types produce clear errors.
- [x] Sort-before-limit and limit-before-sort produce their distinct intended results; sorting is global across all input batches.
- [x] Sorted results retain record identity but do not claim source-cursor eligibility; unbounded/unsupported-source requests are rejected under the finite-source interface.
- [x] Caller tests cover ties, null/missing, mixed numeric types, invalid domains, projected-away keys, empty input, and operation order; documentation states memory and ordering characteristics.

## Resolution

Implemented global Python sort_by with one literal key, direction and independent
missing/null placement. Stable ties use original source ordinals, including repeated
sorts. Numeric ordering retains exact integers; incompatible or nonfinite present
values fail with field/operation errors. Static validation checks field availability.
Explanation reports blocking input-proportional memory and sorted output loses
source-cursor eligibility while retaining identity. Sources must satisfy the existing
finite-source interface; there is no live/unbounded execution mode.

Validation: 329 tests passed on Python 3.13; Ruff and Pyrefly passed; documentation
example and diff whitespace checks passed. Coordinator owns final Python 3.10 checks.
