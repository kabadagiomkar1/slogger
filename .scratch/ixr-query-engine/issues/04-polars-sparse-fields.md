# 04: Preserve sparse and heterogeneous fields in Polars

**What to build:** Polars record queries correctly handle explicit nested paths, missing/null distinctions, and mixed scalar types across evolving batches.

**Blocked by:** 03 (Execute scalar query plans with Polars)

**Status:** ready-for-agent

**Parent specification:** IXR and query execution specification (local tracker, same feature).

**Scope:** Python tooling only; preserve core logging and existing CLI/MCP inputs.

- [ ] Presence/type masks and lossless typed lanes preserve booleans, compatible numbers, strings, nulls, and missing values without global coercion.
- [ ] Literal dotted keys remain distinct from nested mapping paths; non-mapping intermediates are missing. Negated comparisons preserve the reference boolean contract.
- [ ] Late fields/types trigger correct binding or clear unsupported-data errors; no successful partial result is returned on a later unsupported batch.
- [ ] Large integers and mixed numeric conversions are accepted only when lossless; physical metadata slots cannot collide with user keys.
- [ ] Multi-batch caller tests cover absent paths, nulls, heterogeneous values, type changes, and original output reconstruction; backend coverage documentation is updated.
