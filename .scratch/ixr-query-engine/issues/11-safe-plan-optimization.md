# 11: Optimize plans without changing results

**What to build:** Callers benefit from conservative plan simplification while query results, operation order, and errors remain unchanged.

**Blocked by:** 07 (Sort query results in Python), 08 (Group and aggregate in Python)

**Status:** ready-for-agent

**Parent specification:** IXR and query execution specification (local tracker, same feature).

**Scope:** Python tooling only; preserve core logging and existing CLI/MCP inputs.

- [ ] Adjacent pure filters/limits and boolean composition normalize safely; dependency analysis preserves fields required for execution and output.
- [ ] Filters never move across limits. Projection rewrites require valid lineage; transformations preserve missing/null semantics and observable error behavior.
- [ ] Static explanation exposes meaningful logical normalization without reading sources or promising backend-specific speedups.
- [ ] Caller tests compare rewritten/unrewritten results and errors over finite records, closed/open schemas, sorting, grouping, and operation-order edge cases.
- [ ] Native physical optimization remains adapter-owned; documentation separates supported logical rewrites from deferred advanced pushdown.
