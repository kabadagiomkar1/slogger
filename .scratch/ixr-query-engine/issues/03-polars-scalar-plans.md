# 03: Execute scalar query plans with Polars

**What to build:** Callers explicitly select an optional Polars adapter for basic record plans with homogeneous scalar fields and boolean predicates.

**Blocked by:** 02 (Execute basic query plans in Python)

**Status:** resolved

**Parent specification:** IXR and query execution specification (local tracker, same feature).

**Scope:** Python tooling only; preserve core logging and existing CLI/MCP inputs.

- [x] Optional Polars installation supports the required Python versions; base logging/tooling imports work without importing or installing Polars.
- [x] Scan/filter/select/limit lower scalar comparisons, scalar membership, and boolean composition to native expressions without Python object UDFs or silent fallback.
- [x] Original records and source ordinals reconstruct selected output without changing nested values or inserting absent null fields; operation order matches Python.
- [x] Explicit missing-dependency, unsupported operation/data, invalid-plan, and execution errors are distinguishable and retain causes; runtime checks are shown as pending in static explain.
- [x] Shared QueryPlan.execute tests establish Python/Polars parity for the supported subset; documentation lists exact coverage and limitations.

## Resolution

Added explicit optional Polars dispatch and native scalar expressions, batch filtering,
bounded native limits, authoritative record reconstruction and capability/data errors.
The tools-polars extra has a demonstrated Polars 1.29 compatibility floor; imports
remain lazy. Documented supported subset, nullable semantics, precision restrictions,
and filter read-ahead. Sparse/mixed/nested and string/array domains remain explicitly
unsupported until their dependent tickets.

Validation: 355 full tests pass on Python 3.10.20 and 3.13.3 with Polars 1.29.0;
33 adapter tests also pass against Polars 1.44.2. Ruff, Pyrefly and diff checks pass.
