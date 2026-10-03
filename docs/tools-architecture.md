# Tooling implementation ownership

The public interface is `slogger.tools`: construct immutable IXR expressions and
query plans, then call `QueryPlan.execute()` or `QueryPlan.explain()`. Explanation
never reads input. Python is the default; optional Polars is imported only when
selected. Both adapters compile the same IXR without silent fallback.

- `tools/core/` owns IXR, convenient builders, query construction, schema lineage
  validation, conservative normalization, execution coordination, shared row/origin
  contracts, and record projection. Shared contracts do not depend on the dispatcher.
- `tools/sources/` owns finite decoding, deterministic path/glob expansion, rotation
  ordering, concatenation, timestamp merging, diagnostics, and owned-file cleanup.
  Both adapters consume this shared source interface.
- `tools/backends/python/` owns reference compilation, execution, sorting, and
  typed numeric/group reductions.
- `tools/backends/polars/` owns native lowering, typed column binding, execution,
  sorting, and reductions. Original records are retained for exact reconstruction;
  source/order lanes never become application fields.

Builders construct IXR directly. There is no Predicate facade, custom callback,
legacy filtering route, or forwarding module. Adapters remain internal with no
public registration contract.

`PlanResult.records` contains application data; `PlanResult.origins` is aligned by
result position. Filtering, projection, and sorting preserve origins. Aggregation
produces derived rows with `None` origins. Source labels are shared, and original
positions and stable ordinals travel independently of the user schema. A logged
`_id` remains ordinary data.

Source construction is lazy; files/globs are resolved when execution consumes
input. Files and re-iterable collections can be executed again; stdin and iterators
are one-shot. There is no cursor, replay, cache sidecar, raw-line, or live mode.

The migration withdraws legacy filtering, specialized analysis tools, CLI, and
MCP. Grouping does not replace trace/tree reconstruction. Core logging modules,
root exports, compatibility shims, and the emitted log-record schema are unchanged.

See the [public API](api.md), [capability contract](execution-compatibility.md),
[accepted decision](adr/0001-ixr-only-tooling.md), and
[migration specification](../.scratch/ixr-only-tooling/spec.md).
