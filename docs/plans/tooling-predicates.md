> Historical design, superseded by the IXR-only tooling migration. Legacy tools, CLI, and MCP described here have been removed; this is not current usage guidance.

# Rich Python predicates for log tooling

Status: implemented. This document records the delivered design; see
[the API reference](../api.md#typed-ixr-expressions) for usage and matching rules.

## Scope and boundaries

The implementation provides composable, typed record predicates for the Python API in `slogger.tools`.
The core logging library is unchanged: no changes to emission, configuration,
spans, instrumentation, formatting, context injection, root exports, or the log
record schema. New public names belong only in `slogger.tools.__all__`.

CLI syntax, completion, TUI features, and MCP input capabilities are unchanged.
Existing CLI and MCP calls continue working through legacy `Filters`.
No array-element subqueries, type predicates, field-to-field expressions,
fuzzy search, relevance scoring, indexing, or aggregation language in this work.

## Public Python API

```python
from slogger.tools import (
    Field, Filters, Predicate, all_of, any_of, logger_prefix, not_, query,
)

predicate = all_of(
    Field("level").in_(["WARNING", "ERROR"]),
    any_of(
        Field("duration_ms").ge(500),
        Field("error_type").eq("TimeoutError"),
    ),
    Field("request", "method").eq("POST"),
    Field("tags").contains_all(["payment", "retry"]),
    not_(Field("synthetic").eq(True)),
    any_of(logger_prefix("app.pay"), logger_prefix("app.orders")),
)

filters = Filters(level_min=30, predicate=predicate)
page = query("app.log", filters=filters)

# Also usable independently on in-memory records.
records = [{"level": "ERROR", "duration_ms": 900,
            "request": {"method": "POST"}, "tags": ["payment", "retry"],
            "logger": "app.pay"}]
assert predicate.matches(records[0])
matcher = predicate.compile()
selected = [record for record in records if matcher(record)]
description = predicate.explain()
```

`Field(*path)` requires one or more nonempty string segments. `Field("a.b")`
addresses a literal top-level key; `Field("a", "b")` traverses nested mappings.
No automatic dotted-path parsing, array traversal, or numeric indexing initially.

Field methods return immutable `Predicate` objects:

| Methods | Purpose |
| --- | --- |
| `eq`, `ne`, `gt`, `ge`, `lt`, `le` | Typed comparisons |
| `in_`, `not_in` | Scalar membership in a collection of candidate values |
| `exists`, `missing` | Presence checks |
| `regex`, `starts_with` | String matching |
| `contains_any`, `contains_all` | Membership checks on record arrays |

`all_of(*predicates)`, `any_of(*predicates)`, and `not_(predicate)` compose
predicates. `logger_prefix(name)` matches the exact logger or descendants under
`name + "."`; ordinary `starts_with` retains ordinary string-prefix semantics.
Comparison and boolean operators are not overloaded. `bool(predicate)` raises
`TypeError` with guidance to use the composition functions.

Retain `filters=Filters(...)` on existing tools. Direct `filters=predicate` and a
second tool-level `predicate=` parameter are outside this initial API: one entry
point avoids ambiguity and preserves specialized `Filters` attributes.

## Matching contract

- New predicates preserve JSON-compatible operand types without string coercion.
  Numeric comparisons permit integers and floats together, excluding booleans.
  Strings compare with strings; unsupported ordering pairs fail to match.
- Equality distinguishes booleans from numbers, including inside containers.
  Support JSON structural equality for arrays and mappings; scalar `in_` and
  `not_in` accept only scalar candidates and do not search inside record arrays.
- Missing is distinct from `None`. Every field comparison, string operation,
  membership operation, and array operation returns false for missing fields.
  `exists()` matches present null values; `missing()` matches absent paths.
- `ne` and `not_in` return false for incompatible value types. Negation is logical:
  `not_(Field("x").eq(1))` can match missing or incompatible fields.
- Regex uses Python `re.search` on strings only. Compile and reject invalid patterns
  during predicate construction. No implicit stringification of record values.
- Record arrays are lists or tuples for Python callers. `contains_any/all` use
  typed equality, do not recurse, and accept scalar candidates. Duplicated
  candidates do not imply multiplicity requirements.
- Empty `all_of()` matches everything; empty `any_of()` matches nothing.
  For present scalar values, `in_([])` is false and `not_in([])` is true.
  On arrays, `contains_any([])` is false and `contains_all([])` is true.
- Intermediate non-mapping values make nested paths missing. Read records without
  mutation. Invalid query construction raises `ValueError` or `TypeError` before
  consuming a source; ordinary JSON record type mismatches return false.
- Accept finite JSON numbers and JSON-compatible operands; reject arbitrary
  objects and nonfinite numeric operands. Snapshot mutable operands and candidate
  iterables so later caller mutation cannot change a predicate.
- Preserve all legacy `Where` conversion and matching semantics. Do not silently
  redefine old filters in terms of the stricter typed predicates.

## Implemented structure

- `src/slogger/tools/predicates.py` contains the abstract `Predicate` base,
  `Field`, composition functions, and logger helper. A private immutable
  `_Expression` node represents all supported operations; private helpers handle
  operand snapshots, typed equality, and mapping-path resolution.
- Regex patterns compile at construction. `compile()` returns the same reusable
  callable; it resolves the field path against each record. AND/OR short-circuit.
  Compiled state is excluded from expression equality and inspection.
- `Filters.predicate` is optional and appended to the existing constructor fields.
  Legacy conditions AND with it. Matching delegates to the current predicate,
  so assignment or dataclass replacement does not leave stale compiled state.
- New public names are exported only from `slogger.tools`.

## Tool integration audit

Most tools already call `Filters.matches()`: query, summary, meta, fields,
trace, tree, stats, failures, context, diff, tail/follow, and watch. Integration tests cover the shared filtering paths.

- `fields()` inspects dataclass fields to decide whether its unfiltered cache is
  valid. Any supplied predicate disables that cache path; derived state is
  excluded from emptiness detection.
- `tree()` and span-oriented `stats()` replace `Filters(span=None)` and separately
  apply span/window rules. The predicate survives replacement and matches source
  records, not synthetic summaries. Matching records select traces/groups; full
  lifecycle records remain available for reconstruction.
- `trace()` retains its existing filter/grouping restrictions. `context()` always
  retains the requested anchor; predicates select neighbors, while same-trace
  context remains unfiltered.
- Pagination, limits, source order, streaming, and watch behavior must retain their
  existing meanings. Predicate evaluation should not materialize log sources.

## Inspection and compatibility

`Predicate.explain()` returns a detached JSON-compatible description with explicit
path segments and typed values. This is inspection, not query input syntax.
Legacy `Filters.explain()` shape and `Filters.from_mapping()` behavior are preserved
when no predicate is present. Rich explanations add `filters.predicate`, containing
its own `schema_version: 1` and `expression`, while retaining outer schema version 1
under the existing additive tool-output contract. The tool-output schema validates
this extension; the emitted log-record schema is unchanged.

`Filters.from_mapping()` rejects descriptions containing `predicate` rather than
silently discarding it. JSON query loading and MCP predicate inputs remain outside
this implementation.

## Delivery and validation

Completed:

- Predicate model, typed matching, validation, operand snapshots, compilation,
  and short-circuit composition.
- `Filters(predicate=...)` integration, tooling exports, and inspection support.
- Semantic and integration tests for null/missing, nested/literal keys, typed
  equality, arrays, empty collections, logger boundaries, invalid construction,
  cyclic operands, detached explanations, pagination, cache behavior, trace/span
  reconstruction, context, aggregates, and streaming/watch selection.
- API reference, README examples, changelog, and public docstrings.

Implementation validation: **307 tests passed on both Python 3.10 and 3.13**.
Ruff, Pyrefly, `git diff --check`, CLI help, and documented predicate examples
passed. Tests used editable installs without pytest import-path overrides.
These counts record the implementation run, not a claim about future suite size.

The existing reader still materializes in-memory iterables for replay and cursors.
File queries retain streaming and stop at their result limit. No core logging,
CLI input, or MCP input functionality was changed.

## Delivered follow-up

[IXR and query execution](ixr-query-engine.md) separates immutable expression data
from execution and provides validated query plans with Python and optional Polars
adapters. Predicate matching lazily compiles the reference evaluator; native plans
lower IXR into Polars expressions. See the [current API](../api.md).
