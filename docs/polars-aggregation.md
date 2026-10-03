# Native Polars grouping and aggregation

The optional Polars adapter executes `group_by(...).aggregate(...)` and ungrouped
`aggregate(...)` using native global reductions. Count, numeric sum, mean, minimum
and maximum use the same helpers as Python plans. No Python object UDF or automatic
fallback executes reductions.

```python
from slogger.tools import Field, count_rows, mean_of, scan

result = (scan([{"logger": "pay", "duration_ms": 2},
                {"logger": "pay", "duration_ms": 4}])
          .group_by("logger")
          .aggregate(n=count_rows(), avg=mean_of(Field("duration_ms")))
          .execute(backend="polars"))
assert result.records == [{"logger": "pay", "n": 2, "avg": 3.0}]
```

Multiple literal scalar grouping keys are supported. Presence and type columns
keep missing, null, boolean, string and numeric groups distinct. Compatible
integer/float keys merge when they can be represented exactly. Groups retain
first appearance order; original key values come from the first matching input
record. Missing keys remain absent. Aggregate results omit source identity and
can be filtered, projected and limited using the result schema.

Numeric reductions skip missing/null, rejecting other present types and nonfinite
numbers. Empty grouped input yields no rows. Empty ungrouped input yields one row:
count/sum zero, mean/min/max null. Nested paths are supported for reduction fields.
The full upstream input is bound together, so late types and fields cannot silently
change the grouping or reductions across batches.

Integer input lanes must fit signed Int64. Integer sums accumulate natively in
Int128 and are checked to fit signed Int64 before output; overflow raises
`data_incompatible`, never a wrapped result. Python can return larger integer sums.
Mixed integer/float grouping or reductions reject values with magnitude at least
2**53 to avoid lossy integer conversion. Pure integer keys preserve exact identity.
These unsupported domains raise `data_incompatible` without returning partial
results. Mean is floating-point; cross-adapter checks use relative and absolute
`1e-12` tolerance rather than requiring identical reduction order.

Global execution materializes upstream records, columns and native grouping state.
Working memory is proportional to input, and downstream limits do not bound it.
`explain(backend="polars")` reports native global execution and this memory behavior
without consuming sources. Projection, filtering and limits retain builder order.

Both adapters reject nonfinite reduction outputs with `data_incompatible`.
Mean also rejects a nonfinite intermediate sum; native mean does not silently
accept a domain where the Python reference sum/division would overflow.

Native floating sum and mean convert finite binary floats losslessly to a common
power-of-two fixed-point scale, then aggregate native Int128 lanes. This supports
cancellation-sensitive values and repeated fractions without backend floating
accumulation drift. Python performs representation conversion and range checks;
Polars performs every grouped/ungrouped sum and count. No Python UDF or numerical
execution fallback is used. Mean divides the native numerator by scale and the
non-null count; empty means stay null.

Exact native lanes require the common denominator to be at most 2**1023 and the
maximum absolute scaled value times input row count to be below 2**127. Inputs
outside these conservative bounds raise `data_incompatible`, for example extremely
small fractions or widely separated magnitudes that require excessive scaling.
Minimum/maximum do not need fixed-point conversion and retain their existing domain.
Integer-only sum and mean use native Int128 numerators. The Python reference uses
compensated `math.fsum` whenever an input is floating-point; integer-only sums remain
exact. Supported floating reductions are compared at relative/absolute `1e-12`
tolerance across the Python 3.10/Polars 1.29 and Python 3.13/Polars 1.44 endpoints.
