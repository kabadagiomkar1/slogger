> Historical design, superseded by the IXR-only tooling migration. Its legacy compatibility requirements, module paths, examples, and delivery status are not current guidance. See the [current API](../api.md) and [tooling architecture](../tools-architecture.md).

# Native Polars string predicate coverage

Status: implemented. This is a capability note for the Python tooling interface,
not a proposed feature. Core logging and CLI/MCP interfaces are unchanged.

## Supported behavior

`Field(...).starts_with(prefix)` executes natively using a string lane. Matching is
case-sensitive and literal: dots and regex metacharacters in a prefix retain their
ordinary meanings. An empty prefix matches every present string, including an empty
string. Missing, null and non-string scalar values do not match.

`logger_prefix("app.pay")` matches the exact logger name and descendants beginning
with `app.pay.`. It does not match `app.payroll`. The helper lowers to equality OR
prefix matching and uses the same native expressions.

Explicit nested mapping paths, sparse fields, mixed scalar lanes, boolean composition
and logical negation are supported. NOT negates the complete two-valued result, so
negating a string predicate matches missing and non-string scalar values.

## Regex subset

Polars execution supports **plain literal regex patterns only**. Patterns must contain
none of these characters: `. ^ $ * + ? { } [ ] \ | ( )`.

Within this conservative subset, Python `re.search` is a literal substring search.
The adapter executes native string containment with `literal=True`, preserving that
meaning. Empty patterns, Unicode literals, spaces and actual newline characters are
supported. Escapes are not supported, even when they would denote a literal character.

Unsupported patterns raise `ToolError` with `code="expression_unsupported"`, including
the pattern and field path. Rejection happens during execution preparation or static
explanation, before opening or consuming the source. There is no Python UDF or silent
fallback. Invalid Python regex syntax still fails eagerly when creating the predicate.
Python execution retains its full existing regex behavior.

This restriction is intentional: [Polars string containment](https://docs.pola.rs/api/python/stable/reference/expressions/api/polars.Expr.str.contains.html)
uses the Rust regex crate. Accepted native syntax does not prove Python equivalence:
Unicode character classes and end anchors can differ even when both engines accept
the pattern. Coverage can expand only with a demonstrated semantic contract and parity
tests. Current coverage is verified on Polars 1.29.0 and 1.44.2.

## Example

```python
from slogger.tools import Field, logger_prefix, scan

source = [{"logger": "app.pay.worker", "message": "request timeout"},
          {"logger": "app.payroll", "message": "request timeout"}]
result = (scan(source)
          .filter(logger_prefix("app.pay"))
          .filter(Field("message").regex("timeout"))
          .execute(backend="polars"))
assert result.records == [{"logger": "app.pay.worker", "message": "request timeout",
                           "_id": "mem:0"}]
```
