# Query execution capabilities and migration

IXR is the sole expression representation. Convenient builders return immutable
IXR directly; Python and optional Polars consume the same logical query through
internal adapters. Python is the default. Neither adapter silently falls back.

| Capability | Python | Polars |
| --- | --- | --- |
| Typed equality, ordering, scalar membership | Full reference domain, including structural equality | Supported scalar lanes with explicit type/precision limits; structural equality unsupported |
| Presence/missing, nested paths, boolean composition | Supported | Supported; presence-only checks do not require value representation |
| Prefix and logger hierarchy | Supported | Native string lanes |
| Regex | Python regex search | [Plain-literal subset](native-strings.md) |
| Immediate array membership | Supported typed scalar candidates | [Homogeneous scalar arrays](native-arrays.md) |
| Projection and limit | Lazy upstream consumption; materialized output | Native batches may read ahead; materialized output |
| Global stable sorting | Reference numeric/string ordering | [Native domains and precision limits](native-sorting.md) |
| Multi-key grouping and numeric reductions | Typed groups and compensated float reductions | [Native global reductions with checked exact lanes](polars-aggregation.md) |

Both adapters use shared finite source decoding and origin accounting. Full scans
of the same input produce the same skips and warnings. Limited scans may consume
different amounts because native batching and timestamp merging can read ahead.
Files/globs, stdin, finite records, concatenation, and timestamp merging remain
available. Timestamp merging assumes each source is already ordered.

Records contain only application fields. Aligned `PlanResult.origins` locate each
record's file/physical line or iterable/original position; projection and sorting
preserve them. Aggregate rows have `None` origins. An application's `_id` is
ordinary queryable data. Origin itself is not automatically a query field.

Plans retain operation order, closed-schema field validation, missing/null and
bool/number distinctions, stable sort ties, and first-appearance group order.
Static explanation does not consume input and reports pending data checks rather
than claiming runtime compatibility. Global operations materialize upstream input.

Native unsupported expressions raise `expression_unsupported`; incompatible
runtime types or precision domains raise `data_incompatible`. Missing optional
Polars raises `dependency_missing` with its import cause. No automatic engine
selection or public custom-adapter registration is provided.

## Breaking migration

Removed without aliases: Reader, Predicate, Filters/Where, query/Page/summary,
trace/tree/span reconstruction, context selection, stats, failures, diff, field
cache/discovery, validation/rendering helpers, tail/watch, CLI/completion, MCP,
transport schemas, cursors, and replay. Query plans provide retained record
operations and grouping. They do not reconstruct trace trees or watch live files.
Core logging, its schema, and logging compatibility imports are unchanged.

Use the [public API](api.md) and [runnable query example](../examples/query_plans.py).
Designs under `plans/` retain historical evidence and are marked accordingly;
legacy-preservation requirements there are superseded by the
[IXR-only migration](../.scratch/ixr-only-tooling/spec.md).


## Captured investigation delivery

The optional native consumer uses headless `Investigation.open()` for stable
finite regular-file capture and bounded record/diagnostic pages. It preserves
shared UTF-8 decoding and physical origins, with input occurrences and dataset
identities outside application fields. Complete-dataset operations must pass the
shared readiness gate, including during background capture and source verification.
Cancellation and failure preserve an explicitly incomplete browseable prefix;
source/writer resources are released before settled cancellation. See the
[native opening contract](native-investigation.md).
Complete unfiltered trace reconstruction is now delivered through scoped
Investigation jobs and paged trace evidence; it is separate from query grouping
and does not restore the retired legacy tree API. Filtered ancestor context is
explicitly pending. This delivery does not change IXR primitives or the materialized
execution/reduction contracts above.
Captured filters accept existing IXR or shared infix parsing, with explicit
dataset/view scopes and request generations. Reference evaluation runs in an
isolated Python worker with complete disk-backed membership and bounded pages,
preserving original origins/order and typed semantics. This changes no IXR
primitives or materialized execution/reduction contracts above. Optional native
execution remains explicitly available through QueryPlan with the same errors.

Captured discovery indexes every supported mapping path and finite JSON scalar
over the complete dataset, with typed observations, frequency/prefix pages and
explicit index scope/status. IXR's existing array traversal and nonempty-component
constraints apply; collections remain targetable whole fields. Discovery does not
change equality, numeric grouping or missing/null semantics, and extends the shared
grammar completion rather than introducing a predicate engine. CLI/MCP transports
remain deferred. See the [native guide](native-investigation.md).
Captured literal record search has explicitly scoped, complete disk-backed matches
and bounded original-record pages. It reads decoded field names/leaves, uses defined
Unicode literal case/word behavior, and accepts a consumer-supplied console projection.
It neither changes IXR string predicates nor exposes a new execution adapter.

Captured categorical counts use the same reference scalar group identity, retaining
bool/number separation, compatible numeric ties and first-appearance representatives.
Out-of-band exact path bindings support nested/literal selected fields without record
injection. Selected-field presence is a composed consumer scope, preserving public
count_rows and literal-top-level QueryPlan grouping. Complete groups are paged with
None origins; managed disk/working/page exhaustion fails explicitly without publishing
a preview or invalidating prior results.

Captured numeric summaries compose the same selected-field presence guard and
reference validation/finalization over explicit dataset/view scopes. Full validation
precedes metric-order replay; exact integer sums, whole original-sequence compensated
float sums/means, null handling, first min/max ties and overflow errors retain Python
meaning. Managed spill/paging changes delivery, not IXR primitives or adapter
capabilities. Numeric count-only requests still count all present rows.

Native independent aggregate filters compose existing captured filter jobs with
explicit leased input views. Following, detachment and reattachment stay in the
consumer, preserving selected-field presence and categorical/numeric semantics.
Both native editors share whole-dataset discovery; changing Main never relabels
or invalidates a detached successful population. No IXR primitive, materialized
QueryPlan behavior, or backend selection contract changes.
