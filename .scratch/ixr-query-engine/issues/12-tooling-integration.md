# 12: Verify integration with existing tooling

**What to build:** Existing tooling retains its contracts while eligible record operations can use the new execution module only where complete compatibility is established.

**Blocked by:** 05 (Execute string predicates with Polars), 06 (Execute array membership with Polars), 09 (Sort query results with Polars), 10 (Group and aggregate with Polars), 11 (Optimize plans without changing results)

**Status:** resolved

**Parent specification:** IXR and query execution specification (local tracker, same feature).

**Scope:** Python tooling only; preserve core logging and existing CLI/MCP inputs.

- [x] Predicate/Filters matching, legacy Where conversion, custom subclasses, Page metadata, source IDs, cursors, field caches, and concat/time ordering retain their existing behavior.
- [x] Trace/span/context/failures selection preserves required lifecycle and context records; live watch/follow paths remain compatible and do not become arbitrary dataframe plans.
- [x] Any migrated existing operation has verified ordering, source metadata, output shape, and parsing parity; no public backend option is added without complete contract support.
- [x] Shared integration tests cover both adapters through QueryPlan.execute, legacy calls through their current interfaces, optional dependency absence, and failure/resource cleanup.
- [x] Core logging and CLI/MCP inputs are unchanged. Documentation accurately distinguishes the new plan interface, adapter coverage, and preserved legacy execution.

## Resolution

Audited existing execution and retained legacy paths: no cursor/cache/reconstruction
or live operation migrated without complete accounting parity. Added both-adapter
JSONL metadata/cursor-replay tests, seeded sparse/nested typed expression comparisons,
legacy conversion/custom predicate compatibility and native file cleanup coverage.
Existing optional-dependency, trace/context/cache/live checks remain active.

The audit exposed and fixed native presence-only checks rejecting object values:
presence masks now avoid unnecessary value binding, while value operations on the
same path still enforce native supported domains. Focused caller cases protect
parent-presence with nested comparisons and arrays/large integer presence.
Updated execution compatibility documentation and public behavior notes.
Python 3.13 / Polars 1.44.2: 496 tests passed; Ruff/Pyrefly/diff checks passed.
Integration's final matrix owns Python 3.10 and the Polars floor endpoint.
