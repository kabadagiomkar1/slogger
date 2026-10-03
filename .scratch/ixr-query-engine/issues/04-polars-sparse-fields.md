# 04: Preserve sparse and heterogeneous fields in Polars

**What to build:** Polars record queries correctly handle explicit nested paths, missing/null distinctions, and mixed scalar types across evolving batches.

**Blocked by:** 03 (Execute scalar query plans with Polars)

**Status:** resolved

**Parent specification:** IXR and query execution specification (local tracker, same feature).

**Scope:** Python tooling only; preserve core logging and existing CLI/MCP inputs.

- [x] Presence/type masks and lossless typed lanes preserve booleans, compatible numbers, strings, nulls, and missing values without global coercion.
- [x] Literal dotted keys remain distinct from nested mapping paths; non-mapping intermediates are missing. Negated comparisons preserve the reference boolean contract.
- [x] Late fields/types trigger correct binding or clear unsupported-data errors; no successful partial result is returned on a later unsupported batch.
- [x] Large integers and mixed numeric conversions are accepted only when lossless; physical metadata slots cannot collide with user keys.
- [x] Multi-batch caller tests cover absent paths, nulls, heterogeneous values, type changes, and original output reconstruction; backend coverage documentation is updated.

## Resolution

Added private lossless columnar binding with immutable field bindings, presence/null
masks and typed scalar lanes. Native comparisons and membership compose two-valued
masks, retaining missing/null/type semantics. Explicit mapping paths resolve per batch;
late types and fields rebind without global coercion. Original output reconstruction
remains authoritative. Structural value domains and unsafe mixed numeric ranges fail
explicitly until separately supported. Updated existing capability tests/documentation.

Validation: 374 full tests pass on Python 3.10.20 and 3.13.3 with Polars 1.29.0;
45 adapter tests also pass on Polars 1.44.2. Ruff, Pyrefly and diff checks pass.
