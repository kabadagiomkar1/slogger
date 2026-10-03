# 06: Execute array membership with Polars

**What to build:** Callers execute contains-any/all predicates natively with Polars when array types permit exact reference semantics.

**Blocked by:** 04 (Preserve sparse and heterogeneous fields in Polars)

**Status:** resolved

**Parent specification:** IXR and query execution specification (local tracker, same feature).

**Scope:** Python tooling only; preserve core logging and existing CLI/MCP inputs.

- [x] Supported arrays preserve immediate-member typed equality and distinguish booleans from numbers; scalar membership still does not search record arrays.
- [x] Empty candidates, empty arrays, duplicate candidates, null/missing arrays, and incompatible scalar record values match reference behavior.
- [x] Heterogeneous or unsupported nested array domains are rejected clearly unless exact native support is demonstrated; no object UDF fallback is used.
- [x] Shared caller tests span batch changes, nested array fields, any/all composition, negation, and untouched original arrays in output.
- [x] Coverage documentation distinguishes supported native array domains from explicit unsupported cases.

## Resolution

Added native list.contains lowering over homogeneous scalar array lanes with optional
null members. Scalar and array rows, field presence/null and boolean/number identity
remain distinct; empty/duplicate candidates and logical negation match reference
behavior. Scalar membership excludes arrays, including not_in with empty candidates.
Nested paths, tuple preservation, later batch profile changes and original output
shape are covered. Mixed/nested arrays, unsafe numeric comparisons and unsupported
exact integer domains fail explicitly. No object UDF fallback is used.

Validation: 416 tests passed on Python 3.13 with actual Polars 1.29.0; Ruff, Pyrefly,
documentation example and diff whitespace checks passed. Coordinator owns final
Python 3.10/current Polars validation and unified coverage documentation.
