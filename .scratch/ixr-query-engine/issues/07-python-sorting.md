# 07: Sort query results in Python

**What to build:** Callers sort finite record-query results globally, with stable ties and explicit placement of missing/null values.

**Blocked by:** 02 (Execute basic query plans in Python)

**Status:** ready-for-agent

**Parent specification:** IXR and query execution specification (local tracker, same feature).

**Scope:** Python tooling only; preserve core logging and existing CLI/MCP inputs.

- [ ] sort_by supports one literal field, direction, and specified missing/null placement; sort dependencies are validated against the current output schema.
- [ ] Record ties use stable source ordinals. Compatible numbers or strings are ordered; incompatible present types produce clear errors.
- [ ] Sort-before-limit and limit-before-sort produce their distinct intended results; sorting is global across all input batches.
- [ ] Sorted results retain record identity but do not claim source-cursor eligibility; unbounded/unsupported-source requests are rejected under the finite-source interface.
- [ ] Caller tests cover ties, null/missing, mixed numeric types, invalid domains, projected-away keys, empty input, and operation order; documentation states memory and ordering characteristics.
