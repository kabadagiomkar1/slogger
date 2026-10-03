# IXR and query execution specification

Status: approved and published to the local tracker; implementation in progress.
The Predicate/Filters and QueryPlan.execute testing seams were approved.
Predicate IXR is implemented; query-plan interfaces remain planned.

## Problem Statement

Slogger users need richer queries over structured logs without tying their expression
language to Python loops or a particular dataframe library. The existing predicate
engine combines expression data and Python execution closures, making it difficult
to use native dataframe execution while preserving log-specific behavior.

Users also need explicit filtering, projection, sorting, group-by, and aggregation
operations whose ordering is meaningful and whose invalid combinations fail clearly.
Maintainers need one matching contract across execution adapters, preserving missing
fields, typed values, source identity, and existing tooling behavior.

## Solution

Provide an immutable Intermediate Expression Representation (IXR), independent of
execution, behind the existing predicate-building interface. Add immutable query
plans with a small caller interface and interchangeable Python and optional Polars
execution adapters. The execution module handles validation, type binding, conversion,
capability checks, and output reconstruction.

Python remains the default. Supported Polars operations execute natively, exposing
backend optimization opportunities without changing expression semantics. Unsupported
operations or data produce explicit errors. Group-by and aggregation are required
parts of this specification. Existing logging, library calls, and source-cursor
behavior remain compatible.

## User Stories

1. As a library caller, I want to keep constructing predicates with Field and composition helpers, so that existing code remains usable.
2. As a library caller, I want to obtain immutable IXR from a predicate, so that expression meaning is independent of execution.
3. As a library caller, I want typed comparisons, so that strings, numbers, booleans, and null retain their meanings.
4. As a library caller, I want missing and present null to remain distinct, so that sparse logs can be queried accurately.
5. As a library caller, I want literal keys and explicit nested paths, so that dotted field names remain unambiguous.
6. As a library caller, I want scalar membership and array membership to remain separate, so that collection queries behave predictably.
7. As a library caller, I want nested AND, OR, and NOT, so that complex conditions compose without backend-specific syntax.
8. As a library caller, I want regex and prefix behavior to remain explicit, so that adapters cannot silently change matching rules.
9. As a library caller, I want snapshotted operands, so that later mutation cannot change an expression.
10. As a library caller, I want standalone Python matching, so that individual records and streaming tools remain supported.
11. As a custom Predicate author, I want existing subclasses to remain instantiable, so that IXR extraction does not break extensions.
12. As a library caller, I want immutable query construction, so that a query can be extended without altering its parent.
13. As a library caller, I want construction order to define execution meaning, so that limit-before-filter and filter-before-limit remain distinct.
14. As a library caller, I want to project output fields, so that returned records contain the selected information.
15. As a library caller, I want deterministic sorting and limits, so that top-record queries have repeatable ordering.
16. As a library caller, I want grouping by one or multiple fields, so that logs can be summarized by logger or other dimensions.
17. As a library caller, I want named count, sum, mean, minimum, and maximum aggregates, so that summaries are directly usable.
18. As a library caller, I want to filter aggregate results, so that I can select groups based on computed metrics.
19. As a library caller, I want defined empty-input behavior, so that aggregation results require no backend-specific interpretation.
20. As a library caller, I want stable group order and typed group identity, so that grouping does not merge booleans with numbers or missing with null.
21. As a library caller, I want Python or Polars execution selected explicitly, so that dependencies and execution behavior are under my control.
22. As a library caller, I want unsupported operations reported clearly, so that a backend never silently changes my query or falls back.
23. As a library caller, I want original record shapes and identities preserved, so that dataframe conversion does not invent null fields or lose nested values.
24. As a library caller, I want late-arriving fields and type changes handled accurately, so that the first batch does not incorrectly define the entire source.
25. As a library caller, I want invalid field dependencies rejected, so that filtering removed fields or using unavailable aggregate outputs fails clearly.
26. As a library caller, I want static explanation without consuming a source, so that inspection does not exhaust stdin or generators.
27. As a library caller, I want execution metadata and pending capability checks visible, so that explain does not overstate backend support.
28. As a logging-library user, I want dataframe dependencies to remain optional, so that ordinary logging remains lightweight.
29. As a tooling user, I want trace reconstruction and context selection preserved, so that optimizations cannot remove required lifecycle records.
30. As a tooling user, I want existing legacy filters and cursors unchanged, so that this feature does not silently redefine current calls.
31. As a maintainer, I want shared adapter-parity tests, so that execution differences are detected through the caller interface.
32. As a maintainer, I want total-cost benchmarks, so that performance claims include parsing, conversion, execution, and reconstruction.
33. As a library caller, I want accurate documentation of supported backend capabilities, so that proposed features are not mistaken for available ones.

## Implementation Decisions

- The work is confined to the tooling library. Core logging and the emitted record
  contract remain untouched; public tooling names are not exported at the logging root.
- IXR owns frozen logical nodes: Literal, FieldRef, Compare, In, Exists, StringMatch,
  ArrayContains, And, Or, and Not. Closed operator vocabularies exclude arbitrary code.
- Literals preserve typed JSON values, reject cycles/nonfinite operands, and snapshot
  mutable inputs. Numeric equality permits compatible integer/float values while
  keeping booleans distinct, including inside structural values.
- Field references use explicit mapping-path segments. A literal dotted key differs
  from a nested path. Initial expressions do not implicitly traverse arrays.
- Comparison nodes allow two expressions structurally; initial validation restricts
  comparisons to a field value and a literal. Field-to-field expressions are not
  exposed merely because the representation can accommodate them.
- Inequality and exclusion retain explicit operators because they differ from logical
  negation on missing or incompatible values. Missing may lower to negated existence;
  logger hierarchy matching may lower to equality OR a descendant prefix.
- IXR contains no compiled regexes, callbacks, source handles, physical column names,
  or native dataframe expressions. Versioning belongs to an inspection envelope.
  Inspection is not a JSON query-loading contract.
- Predicate remains the existing caller facade. It gains to_ixr; compile lazily caches
  the reusable reference matcher; matches delegates to compile. Regex syntax and
  operand errors still fail at construction. Existing explain shapes are preserved.
- Custom Predicate subclasses without representable IXR remain usable on the existing
  Python matching path. The default to_ixr reports unsupported extraction without
  adding an abstract requirement that breaks subclass instantiation.
- Legacy Filters and Where retain their conversion and matching semantics. Unproven
  translation of legacy clauses to typed IXR is not permitted.
- QueryPlan owns immutable construction and execute/explain entry points. Scan,
  Filter, Project, Sort, Limit, and Aggregate are logical plan nodes. Builder order
  remains semantic rather than being forced into one canonical sequence.
- Group-by is explicit in the caller interface: group_by returns an immutable grouping
  builder, and aggregate completes it. Lowering produces one Aggregate node containing
  ordered grouping keys and named aggregate specifications. Ungrouped aggregation
  is supported directly on a query plan.
- Initial projection selects literal top-level fields; initial sorting selects one key
  with direction and explicit missing/null placement. Grouping supports multiple
  literal field keys. Named computed projections and generalized sorting extensions
  require subsequent specification.
- Aggregate helpers provide row count and numeric sum, mean, minimum, and maximum.
  Aggregation creates an explicit result schema and drops source-record identity.
  Duplicate grouping fields and collisions among group names/aggregate aliases fail.
- Missing and null groups remain distinct; boolean groups differ from numeric groups.
  Compatible numeric values share identity without lossy universal float conversion.
  Only scalar group keys are initially supported. Groups follow first appearance
  unless sorted subsequently.
- Count counts rows. Numeric aggregates ignore missing/null and reject incompatible
  present values, including booleans. Empty ungrouped input yields count/sum zero
  and mean/min/max null; empty grouped input yields no groups. Integer sum/count
  requires exact representability. Floating mean parity uses a documented tolerance.
- Validation tracks schema, dependencies, lineage, ordering, identity, and boundedness.
  Scan schemas are open: unseen fields may be missing. Project/Aggregate schemas are
  explicit: referencing removed or not-yet-created fields is invalid.
- Initial arbitrary-plan execution targets finite sources. Existing live tools retain
  their execution. Global sort/final aggregation requires finite input; a downstream
  limit alone does not bound the input required by either operation.
- The execution module owns the internal adapter seam. Adapters prepare validated
  plans and return executable artifacts that run on a supplied record source and
  expose static explanation. Binding and compiler caches remain implementation details.
- Reader remains responsible for JSONL parsing, source ordering, identity, skipped-line
  accounting, incomplete-line behavior, and owned-resource cleanup. Adapters do not
  independently invent source IDs or introduce a second parser.
- Runtime binding preserves per-row presence/type information and can evolve across
  batches. Profiles are not inferred permanently from the first batch. Unsupported
  later batches fail explicitly without returning a successful partial result.
- The columnar module stores referenced execution fields, masks, and hidden source
  ordinals. Original records remain authoritative for record output. Ordinals map
  selections to records without inventing null-valued absent fields.
- Hidden metadata uses opaque slots outside the user schema. Projection preserves
  hidden record identity, while sorting changes source-order eligibility for cursors.
- Polars is optional and imported only when explicitly selected. Native expressions
  perform supported operations; no Python object UDF fallback or silent coercion is
  used to claim native execution. Regex capabilities and unsupported data domains
  are checked explicitly.
- Python is the default adapter. Explicit Polars requests either preserve the contract
  or raise distinguishable unsupported/incompatible-data errors. No automatic backend
  selection or mixed-engine fallback is introduced.
- QueryPlan execution returns PlanResult with records, schema, warnings, and execution
  metadata. It materializes output; callers use limits where needed. Existing Page
  return values and source-cursor arguments remain unchanged on their current paths.
- Static explanation does not read sources and marks data-dependent checks pending.
  Errors identify logical operations and fields where possible and preserve causes.
- Conservative rewrites may combine adjacent pure filters/limits and simplify boolean
  composition. Filters never cross limits; projection rewrites require resolved field
  lineage. Rewrites cannot change observable errors or missing/null behavior.
- Native top-K is allowed only with matching tie/order semantics. Record ties use
  source ordinals; group ties use first-appearance ordinals. Advanced optimizer work
  is delegated to backend-native plans where semantics permit it.
- Global sorting/grouping operates globally, never as per-batch final results. Partial
  means require sum/count states. Global execution may require input-proportional
  memory initially; explanation, documentation, and benchmarks must state this.
- Eligible existing batch tooling may migrate only after metadata parity is proven.
  Trace/context/live tooling retains its reconstruction and selection behavior.
- Delivery proceeds through IXR extraction, reference record plans, optional Polars
  execution, group-by/aggregation/sorting, then measured integration and documentation.
  No capability is advertised as available before validation and execution support exist.

## Testing Decisions

- Proposed highest testing seam: QueryPlan.execute, using the same logical query and
  sources against both Python and Polars. This seam check remains pending user response.
- Preserve tests through existing Predicate and Filters interfaces for matching and
  compatibility. These existing seams protect standalone matching and tooling calls.
- Good tests assert selected records, ordering, group results, identity, metadata,
  inspection behavior, and errors. They do not depend on private node fields or
  compiler branching. Avoid duplicating each implementation detail in a unit test.
- Existing typed predicate semantic tests and tooling integration tests provide prior
  art for null/missing, typed equality, paths, membership, snapshots, pagination,
  cache eligibility, context, reconstruction, and watch selection.
- Shared expression/plan cases establish adapter parity; deterministic randomized
  cases supplement hand-written semantic edge cases. Floating reduction checks use
  the specified tolerance; integer results require exact equality.
- Test reordered valid plans and invalid dependencies, alias collisions, finite-input
  constraints, unsupported backend requests, and static explanation without source reads.
- Test JSONL and in-memory sources, late field/type changes, sparse nested records,
  incompatible sorting/grouping domains, regex limitations, large integers, and exact
  reconstruction of original output shape.
- Test global sort/aggregation across multiple batches, empty inputs, multi-key groups,
  stable ties/group order, and post-aggregation filtering.
- Use actual Polars execution and temporary JSONL sources for integration tests.
  Conversion-focused tests are justified for lossless behavior; caller tests establish
  end-to-end correctness. Remove obsolete implementation-coupled tests after replacement.
- Retain legacy library, CLI, MCP, source-cursor, field-cache, and custom Predicate
  subclass compatibility coverage without adding new interface features there.
- Check base imports without Polars and explicit optional-adapter installation.
- Run full pytest on Python 3.10 and 3.13, Ruff, Pyrefly, diff checks, CLI help, and
  executable documentation examples. Publish updated capability documentation.
- Benchmark small/large, sparse/homogeneous, selective/nonselective, and repeated
  workloads. Include cold conversion, parsing, planning, execution, reconstruction,
  and peak memory. Avoid brittle timing assertions and unsupported speedup claims.

## Out of Scope

Core logging changes; CLI/TUI/MCP input extensions; pandas execution; automatic
backend selection or silent fallback; a public adapter plugin registry; JSON/SQL
query parsing; arbitrary callbacks in IXR; field-to-field comparisons and arithmetic
in the initial interface; computed projections; joins and window functions;
arbitrary live query plans or unbounded windowed aggregation; dataframe-index-based
source cursors; native file scanners and persistent columnar caches without a
separate source-metadata design; silent replacement of existing stats/summary rules.

## Further Notes

Implementation has started with predicate IXR extraction. Group-by is a required
deliverable, even though it follows reference filtering and backend parity work.

A focused prototype may establish optional-backend version compatibility, type-lane
conversion costs, regex coverage, and memory usage before performance claims. It
cannot redefine the matching contract to accommodate a backend.

Publication is pending because no project issue tracker or triage-label configuration
was provided or found. The to-spec workflow requires tracker setup and publication
with ready-for-agent. Run /setup-matt-pocock-skills to configure that destination.
After the testing seam check, publish this specification and create dependency-linked
tickets; do not treat milestone prose as an existing ticket graph.
