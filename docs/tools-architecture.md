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
  registered operation/result lifecycle, and complete disk-backed trace evidence
  with paged structural/contributor access, decoded literal matching and complete
  disk-backed record-match indexes with explicit projection/view/request scopes,
  exact selected-field categorical counts with typed group identity and derived
  paging, and complete field/scalar discovery with bounded prefix/frequency pages.
  Discovery receives shared grammar context and keeps dataset scope explicit.
  It shares source decoding, imports no Textual, and never
  changes materialized QueryPlan execution.
- `tools/tui/` owns the optional installed native consumer: console formatting,
  virtual viewport, complete JSON presentation, selection, focus, and launch.
  Its public launcher imports Textual lazily. Consumer state is separate from
  captured dataset records. Console options, full visible-field selection policy,
  wrapped-line navigation, bounded viewport layouts, Main editor draft/applied/pending
  state, asynchronous dataset choice publication/menu paging, console/JSON field
  targeting, lower aggregate panes, follow-Main labels and superseding-request
  publication stay in this consumer. Search debounce, current Main linkage,
  focus/options, visible highlighting and navigation remain consumer state;
  headless matching receives a structured console field projection. Syntax-menu
  selection, dismissal, focus and individual editor state also stay here; shared
  grammar completion supplies immutable draft/cursor/replacement context and
  typed insertions independently of terminal libraries or dataset reads. Shared infix
  parsing/path spelling belongs to query core and produces existing IXR nodes.

The [native opening contract](native-investigation.md) uses temporary headless
storage by default and explicit durable cache opt-in; the native launcher defaults
to durable verified reuse. Progressive capture and transactional prefixes remain
browseable; dataset-wide work passes the complete-capture gate. Process leases,
global allocated-disk admission, expiry/clear and independent bounded filter result
workspaces belong to Investigation. Refresh remains a subsequent slice.

The migration withdraws legacy filtering, specialized analysis tools, general
CLI, and MCP. The native application now has its own optional launch entry point. Grouping does not replace trace/tree reconstruction. Core logging modules,
root exports, compatibility shims, and the emitted log-record schema are unchanged.

See the [public API](api.md), [capability contract](execution-compatibility.md),
[accepted decision](adr/0001-ixr-only-tooling.md), and
[migration specification](../.scratch/ixr-only-tooling/spec.md).


Runtime resource configuration remains in `tools/investigation/`: one validated
session operation keeps storage/durable owner budgets coherent, preserves active
memory snapshots, validates captured admission, and shrinks encoded LRU entries.
Persisted native defaults and settings UI stay in `tools/tui/`; imports/path selection
never create configuration files and only explicit save writes defaults. Query,
search, pin and navigation state are consumer session state rather than defaults.
