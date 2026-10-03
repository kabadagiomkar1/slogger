# 08: Group and aggregate in Python

**What to build:** Callers group finite records by one or multiple scalar keys and compute named aggregates, then filter or project the aggregate results.

**Blocked by:** 02 (Execute basic query plans in Python)

**Status:** resolved

**Parent specification:** IXR and query execution specification (local tracker, same feature).

**Scope:** Python tooling only; preserve core logging and existing CLI/MCP inputs.

- [x] group_by returns a non-executable immutable builder completed by aggregate; lowering creates one Aggregate node. Ungrouped aggregation is also supported.
- [x] Row count and numeric sum/mean/min/max follow specified empty-input, null/missing, and incompatible-value rules; integer sums/counts remain exact.
- [x] Grouping distinguishes missing/null and boolean/number while merging compatible numeric values without lossy float conversion; groups follow first source appearance.
- [x] Aggregate schemas omit source identity and reject duplicate keys/alias collisions, references to discarded fields, and array/object grouping keys; post-aggregate filters operate on result fields.
- [x] Caller tests cover multiple keys, empty grouped/ungrouped inputs, stable group order, unsupported domains, aliases, and subsequent filtering/projection/limits; floating tolerance and helper interfaces are documented.

## Resolution

Implemented immutable grouping builders and named Python reductions with typed scalar
group identity, exact integer reductions, schema validation and identity removal.
Updated caller documentation, README and changelog. Python 3.13: 341 tests passed after integration with sorting;
Ruff and Pyrefly passed. Integration will run the Python 3.10 matrix.
