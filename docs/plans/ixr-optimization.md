> Historical design, superseded by the IXR-only tooling migration. Its legacy compatibility requirements, module paths, examples, and delivery status are not current guidance. See the [current API](../api.md) and [tooling architecture](../tools-architecture.md).

# Implemented IXR logical normalization

Status: implemented in query-plan preparation. Core logging, standalone predicate
inspection and legacy tools are unchanged. Normalization runs after validating the
original logical plan and before preparing the explicitly selected adapter.

## Supported rewrites

- Python combines adjacent limits using their minimum and adjacent builtin pure
  filters using ordered AND. Custom predicates and compositions containing them
  remain in their original stages.
- Both adapters collapse adjacent literal projections after validating field
  lineage. Final projection fields determine output schema; hidden record identity
  remains present even when an explicitly selected `_id` is subsequently omitted.
- Builtin boolean expressions flatten same-kind AND/OR nesting, unwrap single-child
  composition and eliminate double negation. Child order and all nonconstant leaf
  dependencies remain unchanged. Original Predicate.explain descriptions remain
  unchanged; the normalized executable expression is separate.
- Polars combines adjacent limits only when the outer limit is redundant or zero.
  A smaller positive outer limit remains separate because native batched limits can
  read ahead through the inner stage. Combining them would change source accounting.

## Deliberately retained stages

Filters never move across limits. Polars filters remain separate: combining them
could profile unsupported values in records already eliminated by the earlier
filter. A logically false constant does not erase a nonconstant branch, because
that would suppress existing adapter binding/capability errors. Projection/filter
pushdown, expression deduplication, branch reordering, and sort/aggregate elimination
are not implemented. A downstream zero limit does not suppress existing blocking
sort or aggregate errors.

Original field validation happens first, so an invalid reference to a field removed
by an earlier projection cannot become valid through rewriting. Sorting errors keep
the original caller-visible operation index, even when preceding operations merge.

## Static explanation and execution

QueryPlan.explain reports normalized operations plus a normalization section with
rewrite names, the original operation count and the original positions contributing
to each executable operation. It does not read files or generators. Required-field
analysis removes discarded projection-only fields while preserving every field
needed by filtering, sorting, grouping, aggregation and output.

No public optimization toggle or backend registration interface is introduced.
Native physical optimization remains adapter-owned. These logical rewrites remove
redundant stages; they are not a claim of a measured backend speedup. Native file
pushdown and more advanced query optimization remain future work.
