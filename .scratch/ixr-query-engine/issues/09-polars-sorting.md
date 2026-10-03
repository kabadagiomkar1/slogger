# 09: Sort query results with Polars

**What to build:** Explicit Polars execution globally sorts record results with the same order and errors as the Python reference adapter.

**Blocked by:** 04 (Preserve sparse and heterogeneous fields in Polars), 07 (Sort query results in Python)

**Status:** ready-for-agent

**Parent specification:** IXR and query execution specification (local tracker, same feature).

**Scope:** Python tooling only; preserve core logging and existing CLI/MCP inputs.

- [ ] Native global sorting preserves direction, explicit null/missing placement, compatible type domains, and source-ordinal ties across batches.
- [ ] Sort/limit order remains semantic; native top-K is used only when equivalent ordering and tie rules are proven.
- [ ] Required sort fields survive execution-column selection even when omitted from output; hidden ordinals reconstruct original records correctly.
- [ ] Unsupported or incompatible sort domains fail clearly; global memory requirements and cursor ineligibility are visible in explanation/documentation.
- [ ] Shared tests compare Python/Polars results for ties, sparse keys, batch changes, empty input, projection dependencies, and sort-limit permutations.
