# 09: Sort query results with Polars

**What to build:** Explicit Polars execution globally sorts record results with the same order and errors as the Python reference adapter.

**Blocked by:** 04 (Preserve sparse and heterogeneous fields in Polars), 07 (Sort query results in Python)

**Status:** resolved

**Parent specification:** IXR and query execution specification (local tracker, same feature).

**Scope:** Python tooling only; preserve core logging and existing CLI/MCP inputs.

- [x] Native global sorting preserves direction, explicit null/missing placement, compatible type domains, and source-ordinal ties across batches.
- [x] Sort/limit order remains semantic; native top-K is used only when equivalent ordering and tie rules are proven.
- [x] Required sort fields survive execution-column selection even when omitted from output; hidden ordinals reconstruct original records correctly.
- [x] Unsupported or incompatible sort domains fail clearly; global memory requirements and cursor ineligibility are visible in explanation/documentation.
- [x] Shared tests compare Python/Polars results for ties, sparse keys, batch changes, empty input, projection dependencies, and sort-limit permutations.

## Resolution

Added native global sorting over exact bound value lanes with separate missing/null
category ranks and source-ordinal ties. Sort/limit order and original reconstruction
remain semantic, including repeated sorts and multi-source input. Numeric-only/string
domains are checked explicitly; unsafe mixed precision and unsupported types fail
with the field and original logical operation index. Static explanation reports
input-proportional working memory and cursor ineligibility. No top-K rewrite is
claimed. Updated capability documentation and removed obsolete unsupported-sort tests.

Validation: 445 full tests pass on Python 3.10.20 and 3.13.3 with Polars 1.29.0;
93 adapter tests pass on Polars 1.44.2. Ruff, Pyrefly, diff checks and the native
sorting documentation example pass.
