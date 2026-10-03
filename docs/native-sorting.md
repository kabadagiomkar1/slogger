# Native Polars global sorting coverage

Status: implemented capability note for the Python tooling interface.

`sort_by()` executes globally with `backend="polars"`, preserving the reference
operation order and original record shapes. All rows reaching a Sort operation are
materialized together; results are never final per-batch sorts.

## Supported domains

- Strings use Unicode lexical ordering, matching Python for valid Unicode strings.
- Integer-only keys retain exact signed Int64 values, including values above 2**53.
- Float-only keys support finite Float64 values.
- Mixed integer/float keys use a native numeric column only when every value has
  magnitude less than 2**53. Larger mixed domains are conservatively rejected to
  avoid lossy ordering. Python execution retains its wider numeric support.
- Missing and null keys are distinct categories and do not constrain the value domain.

Booleans, arrays, objects, nonfinite numbers, integers outside Int64, and mixtures of
string/numeric values raise `ToolError(code="data_incompatible")`. Errors include
the field and original logical operation index, even after plan normalization.
Unsupported precision ranges also produce explicit errors; there is no fallback.

## Ordering and identity

Direction applies only to present values. Missing/null placement is independent of
direction. When both categories are first, missing precedes null; when both are last,
null precedes missing. Ties in every category follow original source traversal ordinals,
including when an earlier sort changed traversal order.

Native execution sorts a category key, the value key, and an opaque source ordinal.
It then reconstructs authoritative records by row indices. Physical keys cannot
collide with user field names. Projection after sorting preserves aligned origins and
absent/nested values without inventing null fields.

A limit before sorting bounds the sort input domain. A limit after sorting still
requires reading and sorting the entire upstream input. No top-K rewrite is claimed
in this delivery. Sort fields removed by projection are rejected before source reads.

## Memory and inspection

Global sorting requires a finite source and memory proportional to its input, in
addition to returned output. Static explanation does not read the source; it reports
`working_memory="input_proportional"` and pending value-domain checks.
Source origin remains preserved. This interface
does not add source cursors or arbitrary live execution.

## Example

```python
from slogger.tools import scan

result = (scan([{"x": 2}, {"x": 1}, {"x": None}, {}])
          .sort_by("x", descending=True, missing="first", nulls="last")
          .execute(backend="polars"))
assert result.records == [{}, {"x": 2}, {"x": 1}, {"x": None}]
assert [origin.position for origin in result.origins] == [3, 0, 1, 2]
```
