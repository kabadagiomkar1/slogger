# Tooling implementation ownership

The public query interface is `slogger.tools`: construct immutable IXR expressions and
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
are one-shot. That finite query source interface has no cursor, replay, cache sidecar,
raw-line, or live mode.

- `tools/investigation/` owns headless stable regular-file capture, bounded disk
  storage/admission, background capture/cancellation, completeness/readiness,
  original origins, and paged records
  and diagnostics, explicit filtered view/job scopes, isolated reference filtering,
  and registered operation/result lifecycle. It shares source decoding, and neither imports Textual nor
  changes materialized QueryPlan execution.
- `tools/tui/` owns the optional installed native consumer: console formatting,
  virtual viewport, complete JSON presentation, selection, focus, and launch.
  Its public launcher imports Textual lazily. Consumer state is separate from
  captured dataset records. Console options, full visible-field selection policy,
  wrapped-line navigation, bounded viewport layouts, Main editor draft/applied/pending
  state and superseding-request publication stay in this consumer. Shared infix
  parsing/path spelling belongs to query core and produces existing IXR nodes.

The initial [native opening contract](native-investigation.md) uses temporary
session storage with synchronous or background capture and transactional prefix
publication. Native loading remains browseable; dataset-wide work passes the
shared complete-capture gate. Bounded IXR jobs, persistent cache reuse/leases,
and refresh are later production slices.

The migration withdraws legacy filtering, specialized analysis tools, general
CLI, and MCP. The native application now has its own optional launch entry point. Grouping does not replace trace/tree reconstruction. Core logging modules,
root exports, compatibility shims, and the emitted log-record schema are unchanged.

See the [public API](api.md), [capability contract](execution-compatibility.md),
[accepted decision](adr/0001-ixr-only-tooling.md), and
[migration specification](../.scratch/ixr-only-tooling/spec.md).
