# 03: Execute scalar query plans with Polars

**What to build:** Callers explicitly select an optional Polars adapter for basic record plans with homogeneous scalar fields and boolean predicates.

**Blocked by:** 02 (Execute basic query plans in Python)

**Status:** ready-for-agent

**Parent specification:** IXR and query execution specification (local tracker, same feature).

**Scope:** Python tooling only; preserve core logging and existing CLI/MCP inputs.

- [ ] Optional Polars installation supports the required Python versions; base logging/tooling imports work without importing or installing Polars.
- [ ] Scan/filter/select/limit lower scalar comparisons, scalar membership, and boolean composition to native expressions without Python object UDFs or silent fallback.
- [ ] Original records and source ordinals reconstruct selected output without changing nested values or inserting absent null fields; operation order matches Python.
- [ ] Explicit missing-dependency, unsupported operation/data, invalid-plan, and execution errors are distinguishable and retain causes; runtime checks are shown as pending in static explain.
- [ ] Shared QueryPlan.execute tests establish Python/Polars parity for the supported subset; documentation lists exact coverage and limitations.
