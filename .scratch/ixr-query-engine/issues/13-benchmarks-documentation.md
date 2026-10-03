# 13: Benchmark and finalize capability documentation

**What to build:** Users receive measured execution tradeoffs and complete, executable documentation of IXR, plans, grouping, and backend coverage.

**Blocked by:** 12 (Verify integration with existing tooling)

**Status:** resolved

**Parent specification:** IXR and query execution specification (local tracker, same feature).

**Scope:** Python tooling only; preserve core logging and existing CLI/MCP inputs.

- [x] Reproducible benchmarks cover small/large, sparse/homogeneous, selective/nonselective, and repeated queries plus sorting/grouping; record methodology and dataset assumptions.
- [x] Report parsing, conversion, planning, execution, reconstruction, total wall time, and peak memory; distinguish cold ingestion from reuse and avoid unsupported speedup claims.
- [x] The public reference, README, release notes, examples, and design/spec status reflect implemented capability and explicit limitations without stale promises.
- [x] Full pytest passes on Python 3.10 and 3.13, Ruff/Pyrefly/diff checks pass, CLI help and documented examples work, and base/optional dependency environments are verified or limitations reported.
- [x] Adapter-parity and compatibility evidence is recorded; defaults remain Python unless a separately authorized decision changes them. No brittle unit-test timing thresholds are introduced.

## Resolution

- `benchmarks/ixr_query_engine.py` generated `benchmarks/results/ixr-2026-10-03.json`: all sixteen 200/100,000-row cases, Python and Polars, three repeats and matching normalized output digests. Methodology and limitations are in `benchmarks/README.md`; independent probes are not added to public total time.
- Initial 3.13.9 / Polars 1.44.2 editable checkout: 496 tests passed; Ruff includes benchmark and example; Pyrefly reports 0 errors (49 existing suppressions). Baseline 9045e18 also passed 496 tests on Python 3.10.20 / Polars 1.29.0. No execution implementation changed in this ticket.
- `examples/query_plans.py` executed successfully with both adapters; CLI help and diff whitespace checks pass. Fresh no-Polars editable installation verified imports, Python filter/count plans, explicit dependency error with ImportError cause and CLI help.
- README, API, release notes, prior predicate design, IXR feature/design/spec and authoritative tracker spec reflect delivered capabilities. Native array capability notes record both tested versions. Python remains default and core logging/production CLI remain unchanged.


### Final review verification

Final numerical/helper fixes at 5e85e48 passed all 507 tests on Python 3.10.20 /
Polars 1.29.0 and Python 3.13.9 / Polars 1.44.2, plus Ruff/Pyrefly/diff checks.
The complete sixteen-case benchmark matrix was rerun at that committed revision;
tracked raw evidence and observation tables now reflect the delivered implementation.
All normalized output digests match. Production execution code was unchanged by
this evidence refresh; Python remains default.
