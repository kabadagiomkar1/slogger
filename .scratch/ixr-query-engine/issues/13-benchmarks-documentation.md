# 13: Benchmark and finalize capability documentation

**What to build:** Users receive measured execution tradeoffs and complete, executable documentation of IXR, plans, grouping, and backend coverage.

**Blocked by:** 12 (Verify integration with existing tooling)

**Status:** ready-for-agent

**Parent specification:** IXR and query execution specification (local tracker, same feature).

**Scope:** Python tooling only; preserve core logging and existing CLI/MCP inputs.

- [ ] Reproducible benchmarks cover small/large, sparse/homogeneous, selective/nonselective, and repeated queries plus sorting/grouping; record methodology and dataset assumptions.
- [ ] Report parsing, conversion, planning, execution, reconstruction, total wall time, and peak memory; distinguish cold ingestion from reuse and avoid unsupported speedup claims.
- [ ] The public reference, README, release notes, examples, and design/spec status reflect implemented capability and explicit limitations without stale promises.
- [ ] Full pytest passes on Python 3.10 and 3.13, Ruff/Pyrefly/diff checks pass, CLI help and documented examples work, and base/optional dependency environments are verified or limitations reported.
- [ ] Adapter-parity and compatibility evidence is recorded; defaults remain Python unless a separately authorized decision changes them. No brittle unit-test timing thresholds are introduced.
