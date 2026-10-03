# Implemented native array membership

Status: implemented for the optional Polars adapter. The Python predicate interface
is unchanged; select Polars explicitly through QueryPlan.execute(backend="polars").
No Python object UDF or silent fallback performs matching.

```python
from slogger.tools import Field, scan

records = [{"tags": ["pay", "retry"]}, {"tags": []}, {}]
result = scan(records).filter(Field("tags").contains_all(["pay", "retry"])).execute(
    backend="polars",
)
assert result.records == [{"tags": ["pay", "retry"], "_id": "mem:0"}]
```

## Supported domains

Each referenced array contains one scalar member type (bool, Int64 integer, finite
float, or string), with optional null members. Empty and null-only arrays are also
supported. Different rows/batches may contain different homogeneous array types,
scalars, missing fields or present null; explicit typed lanes keep them distinct.
Nested mapping paths and literal dotted keys work as before. In-memory tuples use
native list columns internally and retain their original tuple shape in output.

Contains-any/all compares immediate members without candidate multiplicity. Boolean
members are distinct from numbers; compatible integer/float matching uses the same
conservative exactness guard as scalar matching. Cross-numeric matching near or
beyond the exact Float64 integer range (absolute values >=2**53) fails explicitly.
Pure integer matching retains exact Int64 values, including 2**63-1.

Contains-any with no candidates is false; contains-all with no candidates matches
arrays, including empty arrays. Missing fields, present null and scalar fields do
not match either array operation. Null candidates match null members within an
array, not a null-valued field. Masks remain two-valued under AND/OR/NOT.

Scalar in/not-in never search arrays. In particular, not-in with no candidates
matches present scalars including null and excludes arrays. Exists matches present
arrays; negated scalar predicates preserve their defined incompatible-field result.
Original arrays, nested records, absent keys and Reader `_id` values remain intact.

## Explicit limitations

Mixed member types within one array (including bool/int and int/float), nested arrays,
objects, nonfinite numbers and out-of-Int64 integers raise data_incompatible. This
can happen in a later batch; execution fails rather than returning partial success.
Large integer candidates fail static capability checks before reading a source.
A logically incompatible scalar predicate does not bypass referenced-field conversion
checks for an unsupported nested/mixed array.

Native List.contains lowering and its null behavior passed the full behavioral
suite with Polars 1.29.0 on Python 3.10 and Polars 1.44.2 on Python 3.13. Global
sort/group operations must reject array keys/inputs; array support here does not
make array ordering, grouping or structural equality part of their interface.
