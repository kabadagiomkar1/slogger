# 06: Verify the complete IXR-only migration

Status: ready-for-agent
Blocked by: 05

**What to build:** Deliver a verified, installable IXR-only tooling library with preserved query semantics, usable source origins, unchanged core logging, coherent documentation, and measured performance evidence. Close the integration and validation requirements of the [specification](../spec.md).

- [ ] Integrate all preceding tickets and resolve overlapping core/source/adapter changes without restoring compatibility facades or retired imports.
- [ ] Run the full retained test suite on Python 3.10 and 3.13 using editable installed packages, with real optional Polars execution; do not rely on source-path import hacks.
- [ ] Validate base installation/import without Polars, explicit optional-backend selection, distinguishable capability/data errors, and absence of automatic fallback.
- [ ] Confirm adapter parity for expression semantics, schema/dependency validation, operation order, sparse record reconstruction, stable sorting, global grouping/reductions, integer exactness, and cancellation-sensitive floating reductions.
- [ ] Confirm origin alignment and source lifetime/consumption behavior through public queries across files, stdin, iterables, limits, sorting, and aggregation.
- [ ] Run the unchanged core logging regression suite and inspect the diff to confirm emission behavior, root imports, compatibility shims, typed marker, and log-record schema remain intact.
- [ ] Run Ruff, Pyrefly, diff checks, retained runnable examples, and installed-package/export checks. Verify retired transports, dependency extras, schemas, and obsolete tests are absent.
- [ ] Inspect final ownership: query core, finite sources, and separate Python/Polars backends, without a miscellaneous helper pile or forwarding modules carrying old architecture.
- [ ] Run representative small/large end-to-end benchmark cases with correctness digests, both adapters where supported, and origin-handling costs. Record implementation and dependency versions, timing, and memory where available; avoid brittle thresholds and unmeasured speedup claims.
- [ ] Finish the maintained-documentation/link audit and clearly label any retained historical baseline evidence.
- [ ] Resolve discovered regressions and record final validation and any explicit limitations. Do not claim migration completion until every implementation ticket is resolved.

## Implementation guidance

Ticket 05 transitively gates all earlier tickets, so no redundant direct blocking edges are required. This is the final integration/release verification slice, not a substitute for each ticket's own meaningful tests. New features, specialized-tool replacements, public plugins, and core logging changes remain out of scope.
