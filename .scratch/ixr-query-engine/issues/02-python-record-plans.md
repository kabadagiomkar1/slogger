# 02: Execute basic query plans in Python

**What to build:** Callers build immutable scan/filter/select/limit plans, explain them without reading sources, and execute them through the Python reference adapter.

**Blocked by:** 01 (Extract IXR behind existing predicates)

**Status:** resolved

**Parent specification:** IXR and query execution specification (local tracker, same feature).

**Scope:** Python tooling only; preserve core logging and existing CLI/MCP inputs.

- [x] QueryPlan builder order is preserved; filter-before-limit and limit-before-filter have distinct tested results. Plans can be extended without modifying their parents.
- [x] Scan uses the existing Reader source conventions. PlanResult contains records, schema, warnings, and execution metadata; hidden source identity survives projection.
- [x] Open scan schemas permit missing fields; projection creates explicit schemas and references to removed fields fail validation. Invalid arguments and duplicate projection names fail clearly.
- [x] Static explain consumes neither files nor iterators, identifies required fields and pending data checks, and reports ordering/identity/boundedness properties.
- [x] Finite-source execution, file streaming under filter/limit, original record shape, skipped-line metadata, resource cleanup, and unchanged legacy Page/cursor behavior have caller-level tests and documentation.

## Resolution

Implemented immutable Reader-backed scan/filter/select/limit plans with ordered
operations, static schema/dependency validation, source-free explanation, preserved
record identity, streaming Python evaluation and materialized PlanResult metadata.
Added an internal adapter seam and kept the IXR expression compiler unchanged.
Owned Reader iterators close on limits and errors; legacy Page/cursors are untouched.
Updated public documentation and delivery status.

Validation: 322 tests passed on Python 3.13; Ruff and Pyrefly passed; documentation
example and diff whitespace checks passed. Python 3.10 integration validation is
owned by the coordinator at final verification.
