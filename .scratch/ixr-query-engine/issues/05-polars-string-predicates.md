# 05: Execute string predicates with Polars

**What to build:** Callers use string prefix, logger hierarchy, and supported regex predicates with identical results across execution adapters.

**Blocked by:** 04 (Preserve sparse and heterogeneous fields in Polars)

**Status:** ready-for-agent

**Parent specification:** IXR and query execution specification (local tracker, same feature).

**Scope:** Python tooling only; preserve core logging and existing CLI/MCP inputs.

- [ ] Native prefix and logger matching preserve exact-name/descendant distinctions; non-string values do not match.
- [ ] A documented regex subset preserves Python matching semantics; unsupported constructs are detected and rejected rather than translated approximately.
- [ ] Regex errors remain eager at predicate construction; adapter capability errors identify unsupported patterns without Python UDF fallback.
- [ ] Shared tests exercise matches/nonmatches, missing/null, mixed types, nested paths, negation, and regex features both inside and outside supported coverage.
- [ ] Documentation states supported regex behavior and explicit rejection limits; existing Python regex support remains unchanged.
