# 10: Group and aggregate with Polars

**What to build:** Explicit Polars execution supports global multi-key grouping and named aggregates with reference-compatible schemas and semantics.

**Blocked by:** 04 (Preserve sparse and heterogeneous fields in Polars), 08 (Group and aggregate in Python)

**Status:** ready-for-agent

**Parent specification:** IXR and query execution specification (local tracker, same feature).

**Scope:** Python tooling only; preserve core logging and existing CLI/MCP inputs.

- [ ] Grouping and all specified aggregate helpers lower to native operations over the full input; per-batch final aggregation is never returned as a global result.
- [ ] Presence/type encodings preserve group identity, compatible numeric keys, and stable first-appearance order across batches.
- [ ] Empty grouped/ungrouped inputs and incompatible aggregate values follow Python rules; unsupported integer ranges or overflow fail explicitly.
- [ ] Means use correct global sum/count or equivalent native reductions; declared floating tolerance is used for parity while integer results remain exact.
- [ ] Shared caller tests cover multiple keys, aliases, late types, stable group order, all aggregate helpers, and post-aggregate filter/sort/limit behavior where supported; coverage and memory documentation are updated.
