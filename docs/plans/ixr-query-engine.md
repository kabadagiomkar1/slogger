# IXR and interchangeable query execution

Status: implemented. This document preserves the approved design and delivery
requirements; the [current API](../api.md) and [benchmark evidence](../../benchmarks/README.md)
describe delivered capabilities and limitations. Python remains the default; optional
Polars execution supports filtering, projection, limits, global sorting and aggregation.


## Goal and boundaries

Introduce an Intermediate Expression Representation (IXR) that describes typed
expressions independently of their execution engine. Introduce logical query plans
for operations on records. Compile these representations to a reference Python
backend and an optional Polars backend, letting native backend expressions and
query operators use that backend's optimizations.

This work belongs exclusively to `slogger.tools`. Core logging, emission, spans,
configuration, formatting, context injection, root exports, and the emitted
log-record schema remain unchanged. CLI, MCP input, and TUI changes are outside
scope. New public Python names are exported only from `slogger.tools.__all__`.

Keep the current predicate construction API and legacy `Filters` behavior.
Pandas is a future adapter, not part of the initial implementation. IXR must not
encode Polars-specific concepts or promise that every backend supports every node.
Joins, window functions, SQL parsing, arbitrary callbacks, and unbounded windowed
aggregation are outside this delivery.

## Preimplementation baseline (historical)

Before IXR, `predicates.py` combined immutable expression data with precompiled
Python closures. `Filters.matches()` ANDs legacy conditions with a typed predicate.
Most tools already use that shared path. `Reader` supplies record IDs, malformed
line accounting, incomplete-line handling, and concat/time ordering. Query cursors
refer to source positions, not result offsets. In-memory iterables are currently
materialized by the reader.

Trace/span tooling reconstructs complete lifecycles after record-based selection.
`context()` retains its anchor and unfiltered same-trace context. These contracts
must not be changed by dataframe conversion or filter pushdown.

## Architecture

```text
Field / all_of / any_of / not_          Python plan builder
               |                              |
          logical IXR ---------------- logical query plan
                                      |
                           validation and source binding
                                      |
                             bound logical plan
                                      |
                         safe rewrites / capability checks
                                      |
                             backend compilation
                          /                     \
                Python execution          Polars execution
                          \                     /
                      result and source metadata
```

The logical tree contains data only. Bound expressions contain resolved field and
type information. Backend artifacts contain callable closures or native expressions.
Neither binding nor execution mutates the original IXR or logical plan.

## IXR contents

Use immutable, explicitly typed node classes with a closed operator vocabulary:

| Node | Data | Result |
| --- | --- | --- |
| `Literal` | Frozen typed JSON-compatible value | Value |
| `FieldRef` | Tuple of explicit mapping-path segments | Value or missing |
| `Compare` | Operator, left expression, right expression | Boolean |
| `In` | Value expression, tuple of literal scalar candidates | Boolean |
| `Exists` | Field reference | Boolean |
| `StringMatch` | Mode: regex or prefix; input expression and literal pattern | Boolean |
| `ArrayContains` | Any/all mode, input expression, scalar candidates | Boolean |
| `And`, `Or` | Tuple of boolean expressions | Boolean |
| `Not` | One boolean expression | Boolean |

`ne` and `not_in` are distinct operations, not syntactic rewrites to `Not(eq)`
and `Not(in)`: their missing/incompatible-value behavior differs. `missing()`
can lower to `Not(Exists(...))`. `logger_prefix(name)` can lower to exact equality
OR prefix matching with `name + "."`.

Representative proposed structures:

```python
@dataclass(frozen=True)
class FieldRef:
    path: tuple[str, ...]

@dataclass(frozen=True)
class Compare:
    op: ComparisonOp
    left: Expression
    right: Expression

@dataclass(frozen=True)
class And:
    children: tuple[Expression, ...]
```

Design binary comparisons with expressions on both sides. Initially validate
that the right operand is a literal, preserving the supported API. Field-to-field
comparisons and arithmetic remain future expression extensions; having room in
IXR does not mean exposing unimplemented operations.

Logical IXR contains no functions, native dataframe objects, regex caches, source
handles, or physical column names. Equality/fingerprints preserve boolean-vs-number
and literal-path distinctions. Operand snapshots reject cycles and nonfinite values.

Inspection provides a versioned description and `required_fields()` dependency
analysis. Serialization is inspection-only initially; no JSON query loader or
pickle persistence contract is introduced. Keep current `Predicate.explain()` output
compatible; offer IXR inspection separately rather than silently changing its shape.

## Public API and migration

Preserve construction and standalone matching:

```python
predicate = all_of(
    Field("level").in_(["WARNING", "ERROR"]),
    Field("duration_ms").ge(500),
)
expression = predicate.to_ixr()       # new: immutable logical expression
matcher = predicate.compile()        # existing: reusable Python matcher
assert matcher({"level": "ERROR", "duration_ms": 700})
```

Predicate builders validate shape and operands, then build IXR. They do not compile
execution closures during construction. `compile()` lazily compiles/caches the
Python executable, retaining its reusable-callable behavior; invalid regexes still
fail at construction under the existing contract. `matches()` delegates to it.

Custom `Predicate` subclasses implementing the existing abstract interface need
special treatment: give `to_ixr()` a default clear unsupported-expression error,
not a new abstract requirement that prevents existing subclasses from instantiating.
They remain executable on Python; dataframe execution requires representable IXR.

`Filters(predicate=...)` remains supported across existing tools. Legacy `Where`
conversion and regex/stringification behavior do not silently become typed IXR
semantics. Legacy filters stay on their current path until a translation is proven
correct; their presence may make a dataframe request unsupported initially.

Introduce a separate, explicit plan-builder API; the following syntax is available:

```python
plan = (
    scan("app.log")
    .filter(predicate)
    .select("timestamp", "message", "duration_ms")
    .sort_by("duration_ms", descending=True)
    .limit(50)
)
result = plan.execute(backend="polars")
description = plan.explain(backend="polars")
```

Builder calls append operations in the stated order. They do not normalize all
calls into one fixed sequence. Execution is separate from plan creation.
`backend="python"` is the initial default. Explicit `backend="polars"` either
executes with supported semantics or raises a capability error before returning
results. No silent fallback, backend auto-selection, or mixed-engine execution in
this release. A future explicit fallback policy can build on capabilities.

Existing `query(...) -> Page` calls keep their interface and execution by default.
New arbitrary-plan execution returns a separate `PlanResult` with records, schema,
warnings, and execution metadata. It does not automatically claim source-cursor
compatibility. Aggregate result rows have a new schema and no source-record identity.

## Matching semantics and source binding

IXR version 1 preserves the existing typed predicate contract:

- Missing differs from present null. `Exists` includes null. Field comparisons
  fail on missing; `Not` negates the resulting boolean, including missing cases.
- Integers/floats compare numerically; booleans remain separate. No implicit casts
  of strings to numbers. Structural equality retains nested type distinctions.
- Ordering comparisons operate on compatible numbers or strings. Incompatible
  record values produce false for predicates rather than failing the query.
- `ne` and `not_in` fail on incompatible types. Scalar membership does not search
  arrays. Array membership checks immediate members without multiplicity rules.
- Regex/prefix matching requires strings. Python regex semantics remain the public
  contract; an adapter cannot silently replace unsupported pattern features.
- Empty composition and membership retain their documented behavior. Boolean
  predicate outputs are always true/false, not backend-dependent nullable booleans.

Binding produces field slots, possible value types, nullability, presence information,
and conversion requirements. A scan over JSON logs starts with an open schema:
unknown fields are potentially missing, not necessarily invalid. Projection and
aggregation create explicit output schemas; references to removed fields are invalid.

Distinguish logical validation from source-dependent binding. Source inference must
not silently declare a field permanently absent after looking at only the first
batch. Runtime batch schemas may evolve; rebind/cache by the relevant schema signature
or reject incompatible changes clearly. Never coerce a heterogeneous column merely
to make a backend accept it.

## Columnar representation

Keep original records as the authoritative output representation for record queries.
The columnar layer stores the execution fields and a hidden source ordinal/record ID.
A selection mask or ordinal list maps results back to original records without
rewriting user JSON, dropping keys, or adding null-valued keys that were missing.

For referenced paths, preserve:

1. Per-row presence, including failures at intermediate path segments.
2. Per-row type information when heterogeneous values require it.
3. Values in native typed columns where representable without loss.
4. Stable source identity and ordering metadata outside user fields.

Adapters can use presence/type masks and typed value lanes to distinguish missing,
null, booleans, numbers, and strings. Homogeneous inputs can take a simpler native
column path. Use opaque physical column slots so user keys cannot collide with
hidden metadata or dot-separated physical names.

Nested objects, structural equality, heterogeneous arrays, large integers, and
regex features may exceed the initial Polars adapter's exact capabilities. Detect
and reject those combinations rather than using Python object UDFs and claiming
native optimization. Add exact native support incrementally with parity tests.

Start with reader-produced batches to preserve source parsing behavior. This bounds
conversion memory for filter/project execution but cannot provide every scan-level
optimization of a native dataframe scan. A later native source adapter must preserve
record IDs, skipped-line counts, incomplete lines, and ordering before it can replace
Reader. Benchmark ingestion and conversion as well as predicate execution.

## Logical plan nodes

| Node | Required input | Output/properties |
| --- | --- | --- |
| `Scan` | Source descriptor and read options | Open record schema; source identity/order |
| `Filter` | Boolean IXR with available dependencies | Same schema/identity; subset; preserves relative order |
| `Project` | Field selections, later named expressions | Explicit schema; retains hidden identity for record results |
| `Sort` | Available sortable keys and direction/null policy | Defined output order; changes source-order contract |
| `Limit` | Nonnegative count | Prefix of current order; count-bounded output |
| `Aggregate` | Group keys and aggregate specifications | Explicit group/result schema; source identity lost |

The delivery sequence began with Scan, Filter, Project, and Limit, then added
Sort and Aggregate after record-query parity. All six node types are implemented
and validated; backend-specific domain limits remain explicit.

Sort uses explicit null/missing placement and stable source ordinal as the final
tie-breaker for source-record results. Mixed incompatible sort-key types produce a
clear error initially, rather than an accidental Python/backend ordering. Grouped
results can use group keys for deterministic tie-breaking where sortable.

Initial aggregation scope: count of rows, numeric sum/mean, and numeric min/max,
with literal field group keys. Count on empty ungrouped input is zero; numeric sum
is zero and mean/min/max are null when no numeric input exists. Missing/null numeric
inputs are ignored; incompatible present inputs, including booleans, raise a clear
error. Empty grouped input yields no groups. Missing and null grouping values remain
distinct; group identity also distinguishes booleans from numbers. These rules are
new plan semantics, not replacements for existing stats/summary behavior.

## Composition, ordering, and validation

A builder pipeline `scan().filter().select().limit()` lowers to:

```text
Limit(50)
└── Project(timestamp, message)
    └── Filter(level IN [WARNING, ERROR] AND duration_ms >= 500)
        └── Scan(app.log)
```

Data flows bottom-up. Hidden identity survives projection. Fields used only by
filters are execution dependencies even when absent from returned output.

Several orders are valid and intentionally different:

```text
Scan → Filter → Limit          first N matching records
Scan → Limit → Filter          matching records among first N source records
Scan → Sort → Limit            globally first N in sorted order
Scan → Limit → Sort            sort only the first N source records
Scan → Aggregate → Filter      filter group/aggregate results
Scan → Filter → Aggregate      filter records before grouping
```

Reject these before execution:

- Filter/sort refers to a field explicitly removed by Project.
- Filter refers to an aggregate output before Aggregate creates it.
- Sort after Aggregate refers to a discarded source field.
- Filter expression does not produce a boolean; operator operands are invalid.
- Multiple projected outputs have the same name, or aggregate aliases collide
  with each other/group output names.
- Global Sort/final Aggregate is requested directly on an unbounded source without
  a finite boundary. Unknown boundedness must be resolved or rejected for such nodes.
- Selected backend cannot preserve an operation's semantics or represent its data.
- Source-cursor paging is requested after a transformation that changes the required
  identity or ordering, or after aggregation destroys identity.

Track output schema, field lineage, boundedness, ordering, and identity separately.
Limit before Sort provides a finite-count boundary, but an unbounded producer may
still wait indefinitely to deliver N records. Limit after Sort does not make the
sort executable over an unbounded source. Runtime cancellation remains necessary
for live execution; this plan does not introduce live execution of arbitrary plans.

## Safe optimization rules

Do not build a competing dataframe optimizer. Apply a small set of semantic
normalizations and let backend-native plans optimize physical execution.

- Flatten nested AND/OR and simplify boolean constants without changing null rules.
- Combine adjacent pure Filters using AND.
- Move a Filter through Project only when dependencies/aliases can be resolved
  without changing semantics or introducing evaluation errors.
- Move a pure Filter before Sort when the sort domain is valid and no observable
  error behavior changes. Do not move a filter across Limit.
- Combine adjacent Limits using the minimum count.
- Request only required execution/output columns where the source adapter permits it.
- Potential future rewrite: lower Sort + Limit to native top-K only after proving
  identical ordering/ties/null policy. This rewrite is not implemented.

Defer aggregate pushdown and other advanced rewrites. Predicate pushdown must never
remove trace lifecycle or context records needed by higher-level tooling. Rewrites
must account for errors and type domains, not just field names.

## Backend contract and errors

A backend exposes expression/plan capabilities, source/type support, binding,
compilation, execution, and inspection. The capability result reports unsupported
nodes, types, regex features, ordering, or identity requirements with their plan paths.
Compile executable artifacts separately from logical nodes.

Provide distinguishable tooling errors for invalid plan, unsupported backend or
operation, incompatible data, and execution failure. Preserve the underlying cause.
Do not return partially successful results after a backend discovers an unsupported
batch. Inspection can report static capabilities without reading sources; data-bound
inspection explicitly reports when it needs a scan.

Polars is an optional tooling dependency/extra, imported only when selected.
Choose its version range during implementation after checking Python 3.10 support.
No dataframe dependency is required to import slogger or use the Python backend.
Build native expressions, not query strings or eval-generated code.

## Implementation modules

Implemented layout under `src/slogger/tools/`:

```text
predicates.py          builder/facade and lazy reference compilation
ixr.py                 immutable expression nodes and inspection
plan.py                logical nodes, builder and results
_planning.py           validation and plan properties
_optimization.py       conservative normalization
_columnar.py           typed batches, presence and source identity
_execution.py          explicit adapter dispatch
_python_engine.py      reference expression evaluation
_python_plan.py        reference record-plan execution
_sorting.py            reference global sorting
_aggregation.py        reference global aggregation
_polars_engine.py      native expressions and record plans
_polars_sorting.py     native global sorting
_polars_aggregation.py native global aggregation
```

Keep modules focused; split only when needed. Compiler caches belong to execution
artifacts/facades, not IXR equality. Source descriptors are separate from live handles:
plan inspection must not accidentally consume generators or stdin.

## Approved delivery milestones (completed)

### M1 — IXR extraction and reference evaluator

- Introduce nodes, literal snapshots, dependency analysis, and versioned inspection.
- Add `Predicate.to_ixr()` without breaking existing custom subclasses.
- Move Python evaluation to a compiler; preserve eager input/regex validation,
  reusable `compile()`, typed equality, and legacy Filters behavior.
- Port existing predicate tests and add IXR immutability/type tests.

Acceptance: existing tooling behaves identically, construction contains no executable
closures, and standalone/compiled matching agree across the existing fixtures.

### M2 — Logical record plans

- Add Scan/Filter/Project/Limit, builder, plan properties, validation, and PlanResult.
- Implement reference Python execution and conservative normalization.
- Preserve record identity, read ordering, and non-consuming inspection.
- Keep legacy query cursor paths unchanged; new plans do not expose source cursors yet.

Acceptance: alternate valid node orders produce their documented results; removed
field references and malformed plans fail clearly; file filter/limit remains streaming.

### M3 — Optional Polars record execution

- Add lossless batch conversion and explicit backend capability checks.
- Lower supported homogeneous scalar comparisons, membership, presence, boolean
  composition, and string prefix operations to native expressions.
- Add regex, nested paths, and array membership only where exact semantics are proven.
- Execute Scan/Filter/Project/Limit; map selected rows to original records.
- Compare backend results across heterogeneous batches, null/missing, and type changes.

Acceptance: supported plans match Python exactly; unsupported cases fail explicitly;
no silent coercions, Python UDF execution, or cursor changes. Python remains default.

### M4 — Group-by, aggregation, and sorting

- Implement ordering policies, deterministic ties, aggregate output schema and rules.
- Add Python and Polars lowering plus capability validation.
- Reject incompatible domains/unbounded final operations; validate aliases/dependencies.
- Add Top-K lowering only after parity tests.

Acceptance: record sort and grouped outputs match reference semantics; existing
stats/summary APIs remain unchanged until a separate migration is justified.

### M5 — Integration, benchmarking, and documentation

- Route eligible existing batch tool operations through plans only where their full
  metadata/ordering contracts are preserved. Keep trace/context/live paths unchanged
  or use the Python IXR matcher within their existing selection paths.
- Preserve field-cache eligibility, Page metadata, source IDs, and legacy filter
  semantics. Do not add a public backend option to a tool without full contract parity.
- Benchmark parsing, conversion, planning, execution, and total wall time/peak memory.
- Publish backend coverage and limitations; use evidence before changing defaults.

Every milestone updates `docs/api.md`, relevant README Python examples, Unreleased
changelog, public docstrings, and this document's status. Document only implemented
features as available. Do not rewrite historical plans as current API promises.

## Validation and performance evidence

- Shared semantic cases for every supported operator, especially negated missing/null,
  boolean-vs-number, structural values, empty candidates, and logger boundaries.
- Differential tests between Python and Polars for supported expressions/plans;
  deterministic randomized records supplement hand-written edge cases.
- Plan-order tests, projection dependencies, boundedness, aliases, errors, and identity.
- Batch-boundary tests with new fields/types appearing late, large integers, sparse
  nested paths, and lossless output reconstruction.
- Legacy tooling, CLI/MCP regressions, schema inspection, and custom Predicate subclass
  compatibility. No new CLI/MCP functionality.
- Benchmark small/large sources, sparse and homogeneous data, simple and compound
  filters, selective/nonselective predicates, repeated queries, sorting, and grouping.
  Separate cold conversion from reused columnar data. Report full-operation costs;
  do not assert a speedup from dataframe expression timing alone.

Run full pytest on Python 3.10 and 3.13, Ruff, Pyrefly, `git diff --check`, CLI help,
and executable documentation examples. Test optional backend installation separately
from the dependency-free base import. Correctness is required before performance
claims; measure improvements without brittle timing assertions in unit tests.

## Completion criteria

IXR is execution-independent; existing predicate API behavior is preserved; plan
composition is validated; Python and supported Polars operations agree; unsupported
operations are explicit; source identity and missing/null distinctions survive
conversion; optional dependencies stay in tooling; documentation distinguishes
implemented capability from future work. The core logging library is unchanged.

## Draft specification

[The synthesized specification](ixr-spec.md) records the user stories, implementation
decisions, and testing contract. Tracker publication and the testing-seam check are
pending; it is not yet a published ready-for-agent issue.
