# 10: Group and aggregate with Polars

**What to build:** Explicit Polars execution supports global multi-key grouping and named aggregates with reference-compatible schemas and semantics.

**Blocked by:** 04 (Preserve sparse and heterogeneous fields in Polars), 08 (Group and aggregate in Python)

**Status:** resolved

**Parent specification:** IXR and query execution specification (local tracker, same feature).

**Scope:** Python tooling only; preserve core logging and existing CLI/MCP inputs.

- [x] Grouping and all specified aggregate helpers lower to native operations over the full input; per-batch final aggregation is never returned as a global result.
- [x] Presence/type encodings preserve group identity, compatible numeric keys, and stable first-appearance order across batches.
- [x] Empty grouped/ungrouped inputs and incompatible aggregate values follow Python rules; unsupported integer ranges or overflow fail explicitly.
- [x] Means use correct global sum/count or equivalent native reductions; declared floating tolerance is used for parity while integer results remain exact.
- [x] Shared caller tests cover multiple keys, aliases, late types, stable group order, all aggregate helpers, and post-aggregate filter/sort/limit behavior where supported; coverage and memory documentation are updated.

## Resolution

Native global multi-key grouping and all numeric helpers execute through Polars.
Typed presence lanes and first-ordinal reconstruction preserve key meaning and
stable output. Integer sums use Int128 and explicitly reject Int64 output overflow;
unsafe mixed numeric domains reject rather than coerce. Post-aggregate filtering,
projection and limits are covered; sorting is delegated to its native sorting ticket.
Documented memory and numeric limitations. Python 3.13 / Polars 1.44.2: 399 tests
passed; Ruff, Pyrefly and diff checks passed. Integration owns the 3.10/floor matrix.
