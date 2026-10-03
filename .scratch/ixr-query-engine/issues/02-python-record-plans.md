# 02: Execute basic query plans in Python

**What to build:** Callers build immutable scan/filter/select/limit plans, explain them without reading sources, and execute them through the Python reference adapter.

**Blocked by:** 01 (Extract IXR behind existing predicates)

**Status:** ready-for-agent

**Parent specification:** IXR and query execution specification (local tracker, same feature).

**Scope:** Python tooling only; preserve core logging and existing CLI/MCP inputs.

- [ ] QueryPlan builder order is preserved; filter-before-limit and limit-before-filter have distinct tested results. Plans can be extended without modifying their parents.
- [ ] Scan uses the existing Reader source conventions. PlanResult contains records, schema, warnings, and execution metadata; hidden source identity survives projection.
- [ ] Open scan schemas permit missing fields; projection creates explicit schemas and references to removed fields fail validation. Invalid arguments and duplicate projection names fail clearly.
- [ ] Static explain consumes neither files nor iterators, identifies required fields and pending data checks, and reports ordering/identity/boundedness properties.
- [ ] Finite-source execution, file streaming under filter/limit, original record shape, skipped-line metadata, resource cleanup, and unchanged legacy Page/cursor behavior have caller-level tests and documentation.
