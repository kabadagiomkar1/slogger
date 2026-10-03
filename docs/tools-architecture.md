# Tooling implementation ownership

The public query interface remains `slogger.tools`: callers construct plans and use
`QueryPlan.execute()` or `QueryPlan.explain()`. Explanation does not read input.
Python is the default execution adapter; optional Polars is imported only when
selected. Neither adapter silently delegates execution to the other.

The implementation is being migrated according to the IXR-only tooling
specification. The current behavior-preserving prefactor establishes these owners:

- `tools/core/runtime.py` owns execution rows, results, and the internal adapter
  and finite-source protocols. These contracts do not depend on the dispatcher or
  on the file reader implementation.
- `tools/core/fields.py` and `tools/core/rows.py` own shared field access and
  projection. Both adapters use these helpers to preserve record shape.
- `tools/backends/python/` owns reference expression compilation, execution,
  global sorting, and numeric/group reductions.
- `tools/backends/polars/` owns native expression lowering, typed column binding,
  execution, global sorting, and numeric/group reductions. Binding retains the
  original records for lossless reconstruction.
- The execution coordinator selects an adapter, prepares the validated plan,
  owns the finite source lifecycle, and reconstructs the public result. Adapters
  consume the finite-source protocol instead of importing its implementation.

- `tools/core/ixr.py` owns the authoritative immutable expression nodes.
  Convenient builders construct those nodes directly, without a predicate facade.
- `tools/core/plan.py`, `planning.py`, `optimization.py`, and `execution.py`
  own query construction, lineage validation, conservative normalization, and
  adapter coordination. Both adapters compile the expression stored in the plan.

Finite source handling and separate source origin await ticket 04. The current
reader's synthetic identity contract remains temporary. Execution adapters are
internal; there is no public registration interface.

See the [accepted decision](adr/0001-ixr-only-tooling.md) and
[migration specification](../.scratch/ixr-only-tooling/spec.md).

Finite inputs now live in `tools/sources/`: one shared decoder and ordering
module supplies both adapters. Runtime rows carry compact original positions and
shared source-label strings independently of application fields. The public
`PlanResult.origins` collection aligns with records, and derived summaries have
no single origin. No reader compatibility facade, cursor, replay, or live mode
remains. Source construction is lazy; file/glob availability is checked only
when execution starts consuming records.
