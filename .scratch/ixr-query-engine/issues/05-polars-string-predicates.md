# 05: Execute string predicates with Polars

**What to build:** Callers use string prefix, logger hierarchy, and supported regex predicates with identical results across execution adapters.

**Blocked by:** 04 (Preserve sparse and heterogeneous fields in Polars)

**Status:** resolved

**Parent specification:** IXR and query execution specification (local tracker, same feature).

**Scope:** Python tooling only; preserve core logging and existing CLI/MCP inputs.

- [x] Native prefix and logger matching preserve exact-name/descendant distinctions; non-string values do not match.
- [x] A documented regex subset preserves Python matching semantics; unsupported constructs are detected and rejected rather than translated approximately.
- [x] Regex errors remain eager at predicate construction; adapter capability errors identify unsupported patterns without Python UDF fallback.
- [x] Shared tests exercise matches/nonmatches, missing/null, mixed types, nested paths, negation, and regex features both inside and outside supported coverage.
- [x] Documentation states supported regex behavior and explicit rejection limits; existing Python regex support remains unchanged.

## Resolution

Native string lanes now lower prefix and plain-literal regex matching without UDFs.
Logger hierarchy composes native equality and descendant prefix. The proven regex
subset excludes every syntax/escape character; unsupported patterns fail during
preparation/explanation with field and pattern context, before source reads. Python
regex syntax and semantics remain unchanged. Sparse/nested mixed scalar lanes and
negation retain two-valued matching. Added the implemented string capability note,
updated stale interface coverage and executable examples.

Validation: 413 full tests pass on Python 3.10.20 and 3.13.3 with Polars 1.29.0;
72 adapter tests also pass on Polars 1.44.2. Ruff, Pyrefly, diff checks and the new
documentation example pass.
