# IXR implementation design

Status: implementation in progress; predicate IXR and lazy Python compilation
and basic Python record plans are implemented. Sorting, aggregation and Polars
interfaces below remain planned.
Implements the direction in [the feature plan](ixr-query-engine.md). Existing
[typed predicates](../api.md#typed-python-predicates) remain the current interface.

## Design decision

Make query execution a deep module: callers supply an immutable query and choose
an execution adapter; the module owns dependency analysis, validation, source
handling, type binding, conversion, execution, and result reconstruction.

Keep IXR separate from executable artifacts. Backend binding and executable caches
are implementation details. Callers do not orchestrate a sequence of bind, validate,
compile, and run methods merely to execute a query.

There are two justified adapters at the execution seam: reference Python and optional
Polars. There is no public plugin registry or dependency-injection framework yet.
Pandas can become a third adapter without changing IXR or the caller interface.

## Caller interface

Preserve Field/composition/Filters construction and Predicate.matches/compile/explain.
Add Predicate.to_ixr(), scan(), QueryPlan, PlanResult, and aggregate helpers under
`slogger.tools`. Concrete IXR nodes are available in `slogger.tools.ixr` for inspecting
expressions; backend classes and bound nodes remain private.

Proposed record-query usage:

```python
predicate = all_of(
    Field("level").in_(["WARNING", "ERROR"]),
    Field("duration_ms").ge(500),
)
plan = (
    scan("app.log")
    .filter(predicate)
    .select("message", "duration_ms")
    .sort_by("duration_ms", descending=True)
    .limit(50)
)
result = plan.execute(backend="polars")
explanation = plan.explain(backend="polars")
```

Group-by is part of delivery, with an explicit caller interface:

```python
plan = (
    scan("app.log")
    .filter(Field("level").eq("ERROR"))
    .group_by("logger")
    .aggregate(error_count=count_rows(), average_ms=mean_of(Field("duration_ms")))
    .filter(Field("error_count").gt(10))
    .sort_by("error_count", descending=True)
)
result = plan.execute(backend="polars")
```

`group_by(*keys)` returns an immutable grouping builder whose only operation is
`aggregate(**named_aggregates)`. It is not an executable GroupBy plan node; calling
aggregate creates one Aggregate node containing both keys and aggregates. Multiple
keys are supported. `QueryPlan.aggregate(...)` provides ungrouped aggregation.
Aggregate helpers: count_rows(), sum_of(field), mean_of(field), min_of(field),
max_of(field). Fields are explicit Field objects when paths are nested.

Initially select accepts literal top-level key names, sort_by accepts one literal
key plus direction and missing/null placement, and group_by accepts literal key
names. Named computed projections and multiple sort keys can follow when specified;
the private plan representation supports tuples of sort keys from the outset.

QueryPlan methods return new plans; call order is semantic. No reads occur during
construction or static explain. execute returns all selected output records in a
PlanResult; callers should use limit when output size must be bounded. Python is
the default adapter. Explicit Polars execution never silently falls back to Python.
Source cursor arguments are absent from this new interface initially.

## Module ownership and locality

| Module | Owns | Interface to other modules |
| --- | --- | --- |
| ixr.py | Frozen logical expressions and typed literals | Nodes, validation, dependencies, inspection |
| predicates.py | Existing caller facade, early validation, lazy Python matcher | Field and Predicate behavior |
| plan.py | Immutable builder and logical plan nodes | scan, QueryPlan, PlanResult, aggregate helpers |
| _planning.py | Plan properties, validation, conservative normalization | Prepared logical plan |
| _execution.py | Adapter dispatch, source lifecycle, result/error handling | Execute/explain functions used by QueryPlan |
| _python_engine.py | Reference expression and plan evaluation | Internal execution adapter |
| _polars_engine.py | Native expression/plan lowering and runtime binding | Internal execution adapter |
| _columnar.py | Lossless referenced-field batches and source identity | Batches and binding metadata for Polars |

The execution seam belongs inside the execution module, not at every tooling call
site. Source parsing stays with Reader. Do not add a second JSONL parser or spread
presence/type conversion into query, stats, trace, and watch.

If the execution module disappeared, each caller would need to coordinate adapter
capabilities, source ownership, binding, and output reconstruction. That is the
behavior it hides, and the leverage it provides. Lightweight facade methods are
acceptable because callers cross one coherent interface rather than several stages.

## IXR representation

Use frozen dataclasses for FieldRef, Literal, Compare, In, Exists, StringMatch,
ArrayContains, And, Or, and Not. Use explicit enums or Literal types for closed
operator sets. A tagged literal distinguishes null, bool, number, string, array,
and object. Arrays use frozen tuples; objects use canonical key/value tuples.
Numeric literals retain their original value without lossy float conversion.

FieldRef stores a tuple of mapping path segments. Field("a.b") is one segment;
Field("a", "b") is two. No dotted-path parser or implicit array traversal.

Both ne and not_in have explicit operators. Missing lowers to Not(Exists).
Logger hierarchy matching lowers to equality OR starts-with(name + ".").
Comparisons allow two expression operands structurally but version-1 validation
permits a field value and a literal only. Boolean child expressions are immutable.

Keep versioning on the inspection envelope, not duplicated on every node. IXR
inspection is not a JSON loader contract. Predicate.explain keeps its existing
output vocabulary; a facade visitor derives it from IXR. Equality ignores caches
and preserves all meaningful typed distinctions. Do not promise public hashability
or cross-process executable caching until numeric canonicalization is specified.

## Predicate migration

Replace the private executable _Expression with a facade storing logical IXR and
an optional private Python matcher cache. Construction still validates operand
snapshots and Python regex syntax immediately. Execution compilation is lazy.

The Python compiler becomes the single reference implementation of typed matching;
do not leave another typed evaluator in predicates.py. Predicate.matches() uses
compile(), which returns the cached callable. The logical tree contains no callbacks.

Predicate.to_ixr() has a default unsupported-expression error on the abstract base,
not a new abstract method. Existing custom subclasses remain usable through matches
and compile; dataframe execution rejects subclasses without representable IXR.

Filters remains a compatibility module. Legacy Where conversion continues on its
current path; converting Where to typed Compare would change behavior. Existing
tools can gain reference IXR evaluation through Predicate without plan rewrites.

## Internal execution seam

Use a small private adapter interface, implemented by Python and Polars:

```python
class ExecutionAdapter(Protocol):
    def prepare(self, plan: ValidatedPlan) -> PreparedExecution: ...

class PreparedExecution(Protocol):
    def run(self, source: RecordSource) -> ExecutionResult: ...
    def explain(self) -> dict[str, object]: ...
```

prepare handles static capabilities and returns an adapter-owned executable artifact.
Runtime binding belongs inside run, because source records can introduce new fields
and types. No Polars Expr objects escape through the result or logical plan.

The execution module resolves the requested adapter, validates logical dependencies,
prepares it, opens the source through Reader, runs it, reconstructs PlanResult, and
closes owned resources even on failure. Pass RecordSource into the prepared adapter;
do not let adapters open global files or invent source IDs independently.

Static explain calls prepare/explain without opening the source. It reports runtime
checks as pending, rather than claiming inferred support. Data-bound profiling is
a separate future operation; explain must not consume a generator or stdin.

## Validation and binding

Compute each node's output schema, required fields, ordering, identity, and boundedness.
Scan has an open schema: a never-seen key can be missing. Project/Aggregate close
that schema, so references to discarded fields are invalid. Hidden identity is
outside the user schema and cannot satisfy arbitrary user field references.

Binding at runtime associates FieldRef with value lanes, presence masks, type masks,
and physical slots. A missing source path differs from a path removed by Project.
Batch-local type profiles may differ; cache executable lowering by the referenced
profile, not the first batch alone. Late unsupported types cause an explicit error,
not coercion or partial output. Source bytes may have been read by then; execution
is not rolled back, but no successful PlanResult is returned.

Limit gives a count bound; a finite source gives an input bound. Keep these facts
separate from cancellation/termination. This release executes finite query plans;
arbitrary live sources, even with Limit, are outside its interface. Existing live
tooling keeps its implementation. Sort and final aggregation need finite input.

Unsupported adapter/operation, invalid plan, incompatible data, and execution failure
use distinguishable ToolError codes and retain causes. Errors identify the logical
node/path and referenced field where possible.

## Dataframe execution design

Batch filter/projection/limit keeps original records only for the current batch plus
selected output. Build typed columns for referenced fields, presence/type masks,
and hidden source ordinals. Select output using ordinals; reconstruct from original
records, preserving absent keys, nested JSON, and _id.

Homogeneous fields take a native fast path. Mixed fields require exact typed lanes,
or an explicit unsupported-data error. A mask implementing eq must already be a
non-nullable boolean before applying Not; simply negating a backend nullable
comparison would change the contract. Python regex features unsupported by the
Polars adapter are rejected. Native support is required: no Python object UDF fallback.

The optional adapter imports Polars only when selected. The first batch path lowers
operators to native expressions on each batch; global sort/grouping builds a native
lazy plan over compatible batch data or materializes execution columns as required.
Batch-local aggregates may be merged only with correct aggregate states: mean needs
sum and count, not a mean of batch means. No per-batch final sorting or aggregation
is presented as a global result.

Initially global operations may require memory proportional to input. Report this
through explanation/documentation and benchmark it. Batching alone does not make
sort/grouping bounded-memory. Native file scans and persistent columnar caches are
separate follow-ups, because their source metadata contracts require additional work.

## Grouping and aggregation semantics

Aggregate contains input, ordered grouping fields, and named aggregate specifications.
The grouping builder disappears during lowering. Aggregate outputs grouping fields
plus aliases and drops source identity. Duplicate keys/aliases and naming collisions
are validation errors. Further Filter/Project/Sort operates on this new schema.

Group identity distinguishes missing from null and bool from number; compatible
numeric values such as 1 and 1.0 share a group without converting all integers to
floats. Support scalar grouping keys first; array/object group keys are rejected.
Grouped output follows first group appearance in source order for both adapters
unless a subsequent Sort specifies another order. This makes group-row Limit
meaningful and consistent without requiring keys to be mutually sortable.

Count counts rows. Numeric operations ignore missing/null but reject incompatible
present values including booleans. Empty ungrouped input yields count=0, sum=0,
and mean/min/max=null; empty grouped input yields no groups. Sum/count on integer
inputs require exact semantics; overflow/unsupported large integers fail explicitly
in adapters that cannot represent them. Mean is floating-point and backend parity
uses a documented tolerance, not a claim of bit-identical reduction order.

## Ordering and safe rewrites

Preserve builder order in the logical plan. Combine adjacent pure Filters and Limits;
flatten boolean composition. Move a Filter across Project only with valid field
lineage. Do not move it across Limit. Do not reorder expressions whose runtime errors
would become observable on a different input domain.

Sort retains original-record identity but changes ordering and source-cursor eligibility.
Ties on record results use source ordinal. Initial sorting supports compatible numeric
or string values per key, with explicit missing/null placement; incompatible types
are errors. After aggregation ties use first-group-appearance ordinal. Top-K is an
adapter optimization only when it preserves these rules.

No filter pushdown into trace reconstruction. Trace/context/failures selection retains
full lifecycle/context records through existing tooling. Initial plan integration is
opt-in and limited to record queries with proven metadata parity.

## Test surface and delivery slices

Tests cross Predicate and QueryPlan interfaces. Do not duplicate all behavior by
asserting private dataclass fields or compiler implementation details. Internal
conversion tests are warranted for lossless round trips, but caller-level tests
prove that those details yield correct outputs.

1. Extract IXR behind the existing predicate interface. Existing tests remain the
   behavioral contract; add to_ixr/dependency/inspection and custom-subclass tests.
2. Implement scan/filter/select/limit with the Python adapter. Test reordered plans,
   validation, output identity, malformed input metadata, and non-consuming explain.
3. Implement the Polars adapter for an explicit supported subset. Run the same cases
   through both adapters; test missing/null/late type changes and explicit errors.
4. Implement group_by/aggregate and sort through both adapters. Test empty input,
   multiple keys, alias collisions, type distinctions, reduction tolerance, stable
   groups/ties, and global rather than batch-local results.
5. Benchmark full execution costs and integrate only eligible tooling paths. Update
   interface documentation, optional-dependency coverage, and plan status.

Use real temporary JSONL sources and actual Polars execution in integration tests.
These dependencies are local/in-process, not remote mocked adapters. Adapter parity
is observable through the same plan.execute interface. Remove implementation-coupled
tests made obsolete by the refactor; retain legacy behavior coverage.

Run pytest on Python 3.10 and 3.13, Ruff, Pyrefly, CLI help, diff checks, and executable
interface examples. Benchmark parsing, conversion, execution, output reconstruction,
and memory together. The core logging library and CLI/MCP inputs remain untouched.

## Alternatives and remaining evidence

Rejected: exposing bind/compile/run as required caller stages; dataframe objects as
IXR; backend callbacks inside expression nodes; automatic casts/fallback; translating
legacy Where without parity; introducing a plugin registry before a third adapter.

A focused prototype should establish the supported Polars version/type range,
heterogeneous lane conversion cost, regex capability checks, and global-operation
memory cost. These measurements refine adapter coverage and performance claims;
they do not change the logical matching contract. Group-by is required in the
implementation specification, rather than a deferred feature.
