# 12: Verify integration with existing tooling

**What to build:** Existing tooling retains its contracts while eligible record operations can use the new execution module only where complete compatibility is established.

**Blocked by:** 05 (Execute string predicates with Polars), 06 (Execute array membership with Polars), 09 (Sort query results with Polars), 10 (Group and aggregate with Polars), 11 (Optimize plans without changing results)

**Status:** ready-for-agent

**Parent specification:** IXR and query execution specification (local tracker, same feature).

**Scope:** Python tooling only; preserve core logging and existing CLI/MCP inputs.

- [ ] Predicate/Filters matching, legacy Where conversion, custom subclasses, Page metadata, source IDs, cursors, field caches, and concat/time ordering retain their existing behavior.
- [ ] Trace/span/context/failures selection preserves required lifecycle and context records; live watch/follow paths remain compatible and do not become arbitrary dataframe plans.
- [ ] Any migrated existing operation has verified ordering, source metadata, output shape, and parsing parity; no public backend option is added without complete contract support.
- [ ] Shared integration tests cover both adapters through QueryPlan.execute, legacy calls through their current interfaces, optional dependency absence, and failure/resource cleanup.
- [ ] Core logging and CLI/MCP inputs are unchanged. Documentation accurately distinguishes the new plan interface, adapter coverage, and preserved legacy execution.
