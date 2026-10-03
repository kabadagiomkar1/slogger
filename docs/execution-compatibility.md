# Query execution compatibility

The immutable query-plan interface and the existing tooling interface coexist.
No existing operation was migrated to dataframe execution: Reader metadata, legacy
filter conversion, source cursors, field caches and reconstruction remain on their
established paths. Core logging and CLI/MCP inputs are unchanged.

| Interface | Execution and preserved contract |
| --- | --- |
| Predicate.matches / Filters.matches | Existing standalone Python matching, including custom Predicate subclasses |
| query / tail_once | Page output, source IDs, complete/incomplete cursor conventions and parsing metadata |
| fields | Existing cache eligibility and invalidation; predicate-filtered calls do not overwrite the unfiltered cache |
| trace / tree / span stats / failures | Existing lifecycle reconstruction and selection semantics |
| context | Anchors and trace/neighborhood selection retained |
| watch / follow | Existing live execution; no arbitrary dataframe query plans |
| QueryPlan.execute | Explicit Python/Polars adapter, PlanResult output and no source-cursor argument |

A legacy Where clause may coerce values according to its existing contract. Typed
IXR does not silently replace that contract. Existing custom Predicate subclasses
continue to match through Filters; a query plan requires representable IXR and
reports `expression_unsupported` when a custom subclass has no IXR representation.
A subclass that supplies IXR must ensure its representation means the same thing
as its reference matcher.

Both plan adapters share Reader parsing, concat/time source ordering and record IDs.
Full scans report matching skipped-line and warning accounting. A downstream native
filter limit may read ahead in batches, so limited plan accounting must not be
assumed equal to legacy query accounting. One-shot sources are consumed on execute.
Returned identity and shapes remain original records for record operations;
aggregation creates new records and sorting changes source-cursor eligibility.

Presence-only native expressions bind only masks: object-valued fields, nested
containers, heterogeneous arrays and integers outside native numeric ranges can
be checked with exists/missing. A nested field predicate does not require the parent
object itself to be represented natively. If the identical path also participates
in a value comparison, string or array operation, its value must fit the documented
native domain; unsupported values still fail explicitly.

Compatibility is verified through public calls: JSONL source selection and legacy
cursor replay, seeded sparse nested typed expressions across multiple batches,
custom predicates and legacy Where conversion, and owned-file cleanup after limits
and native data failures. Existing trace/context/cache/live tests remain in the full
suite, as does a fresh-interpreter test of optional dependency absence. Tests do not
require native representation of discarded or unrelated user fields.
