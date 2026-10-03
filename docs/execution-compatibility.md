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
