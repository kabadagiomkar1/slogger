# 05: Finish documentation, examples, and benchmark migration

Status: ready-for-agent
Blocked by: 03, 04

**What to build:** A reader can learn, run, and measure the final IXR-only library using maintained project guidance without encountering removed interfaces or confusing historical compatibility requirements. Complete the documentation and runnable-artifact migration required by the [specification](../spec.md).

- [ ] Maintained public API guidance, README, changelog, and capability documents consistently describe direct IXR builders, query operations, Python/optional Polars, and separate source origins.
- [ ] Explain files/globs/stdin/iterables, concatenation versus timestamp merging, one-shot versus reusable inputs, lazy construction, operation-dependent materialization, diagnostics, and resource ownership accurately.
- [ ] Clearly explain removed filtering/specialized/transport interfaces and the origin result change. Do not imply grouping replaces trace/tree reconstruction or advertise planned replacements as implemented.
- [ ] Remove obsolete transport instructions and recipes, or explicitly archive them as historical. Mark retained completed designs as superseded for legacy-preservation requirements and remove misleading current-use links.
- [ ] Runnable examples and benchmark entry points import only the retained public library and execute successfully against the final result/origin contract.
- [ ] Benchmark correctness checks compare application data and relevant ordering/origin semantics without synthetic identity assumptions. Measurement guidance includes parsing, conversion, origin handling, execution, reconstruction, and memory where available.
- [ ] Do not carry forward speedup claims or benchmark evidence as if measured against the new implementation; label retained historical measurements accurately.
- [ ] Agent navigation and development commands reflect the core/source/backend organization and omit retired CLI checks while preserving installed-package testing conventions.
- [ ] Audit packaging metadata, shipped schemas, optional extras, and documentation links for residual transport references. Retain core schema/type package data and the Polars extra.
- [ ] Verify examples and documented public names against installed base and optional-backend environments; audit maintained material for removed imports and stale claims.

## Implementation guidance

Earlier tickets update guidance directly affected by their behavior changes. This ticket is the final comprehensive reconciliation once both expression and source/result contracts are established. Documentation of core logging must remain accurate and its behavior unchanged.
