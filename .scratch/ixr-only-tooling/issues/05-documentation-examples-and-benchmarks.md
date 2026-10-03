# 05: Finish documentation, examples, and benchmark migration

Status: resolved
Blocked by: 03, 04

**What to build:** A reader can learn, run, and measure the final IXR-only library using maintained project guidance without encountering removed interfaces or confusing historical compatibility requirements. Complete the documentation and runnable-artifact migration required by the [specification](../spec.md).

- [x] Maintained public API guidance, README, changelog, and capability documents consistently describe direct IXR builders, query operations, Python/optional Polars, and separate source origins.
- [x] Explain files/globs/stdin/iterables, concatenation versus timestamp merging, one-shot versus reusable inputs, lazy construction, operation-dependent materialization, diagnostics, and resource ownership accurately.
- [x] Clearly explain removed filtering/specialized/transport interfaces and the origin result change. Do not imply grouping replaces trace/tree reconstruction or advertise planned replacements as implemented.
- [x] Remove obsolete transport instructions and recipes, or explicitly archive them as historical. Mark retained completed designs as superseded for legacy-preservation requirements and remove misleading current-use links.
- [x] Runnable examples and benchmark entry points import only the retained public library and execute successfully against the final result/origin contract.
- [x] Benchmark correctness checks compare application data and relevant ordering/origin semantics without synthetic identity assumptions. Measurement guidance includes parsing, conversion, origin handling, execution, reconstruction, and memory where available.
- [x] Do not carry forward speedup claims or benchmark evidence as if measured against the new implementation; label retained historical measurements accurately.
- [x] Agent navigation and development commands reflect the core/source/backend organization and omit retired CLI checks while preserving installed-package testing conventions.
- [x] Audit packaging metadata, shipped schemas, optional extras, and documentation links for residual transport references. Retain core schema/type package data and the Polars extra.
- [x] Verify examples and documented public names against installed base and optional-backend environments; audit maintained material for removed imports and stale claims.

## Implementation guidance

Earlier tickets update guidance directly affected by their behavior changes. This ticket is the final comprehensive reconciliation once both expression and source/result contracts are established. Documentation of core logging must remain accurate and its behavior unchanged.


## Resolution

Reconciled maintained README/API, ownership/capability guidance, changelog, ADR,
and agent navigation with direct IXR and finite sources with aligned origins.
Maintained native capability notes now have corrected executable origin examples;
all prior completed plans/reviews carry historical supersession notices. Local
Markdown link targets were checked, and packaging retains only dev/examples/
tools-polars extras plus the core schema and typed marker, with no transport extras.

The benchmark harness now imports the actual core/source/backend owners, measures
origin-aware source ingestion and packaging, and compares ordered records plus
origins. Application `_id` data is left intact. File positions are checked against
independently generated record indices; aggregate origins must be absent. Prior
version-1 raw timings are explicitly historical, with no new speedup claim.

Validation: the old benchmark failed on deleted imports before repair. The repaired
16-case smoke matrix (200/300 rows, both adapters, one repeat) passed matching
record/origin digests. Query examples ran on Python and Polars, and in a fresh
editable base install without Polars. All four maintained native capability snippets
executed successfully. Public exports were checked in base/optional environments.
The retained suite passed 319 tests on Python 3.13/Polars 1.44.2; Ruff passed across
source/tests/examples/benchmarks, Pyrefly reported zero errors, and diff checks
passed. Full version/performance evidence is owned by ticket 06.
