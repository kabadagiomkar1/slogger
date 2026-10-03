# 06: Execute array membership with Polars

**What to build:** Callers execute contains-any/all predicates natively with Polars when array types permit exact reference semantics.

**Blocked by:** 04 (Preserve sparse and heterogeneous fields in Polars)

**Status:** ready-for-agent

**Parent specification:** IXR and query execution specification (local tracker, same feature).

**Scope:** Python tooling only; preserve core logging and existing CLI/MCP inputs.

- [ ] Supported arrays preserve immediate-member typed equality and distinguish booleans from numbers; scalar membership still does not search record arrays.
- [ ] Empty candidates, empty arrays, duplicate candidates, null/missing arrays, and incompatible scalar record values match reference behavior.
- [ ] Heterogeneous or unsupported nested array domains are rejected clearly unless exact native support is demonstrated; no object UDF fallback is used.
- [ ] Shared caller tests span batch changes, nested array fields, any/all composition, negation, and untouched original arrays in output.
- [ ] Coverage documentation distinguishes supported native array domains from explicit unsupported cases.
