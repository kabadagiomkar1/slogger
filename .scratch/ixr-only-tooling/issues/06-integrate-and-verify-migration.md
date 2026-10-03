# 06: Verify the complete IXR-only migration

Status: resolved
Blocked by: 05

**What to build:** Deliver a verified, installable IXR-only tooling library with preserved query semantics, usable source origins, unchanged core logging, coherent documentation, and measured performance evidence. Close the integration and validation requirements of the [specification](../spec.md).

- [x] Integrate all preceding tickets and resolve overlapping core/source/adapter changes without restoring compatibility facades or retired imports.
- [x] Run the full retained test suite on Python 3.10 and 3.13 using editable installed packages, with real optional Polars execution; do not rely on source-path import hacks.
- [x] Validate base installation/import without Polars, explicit optional-backend selection, distinguishable capability/data errors, and absence of automatic fallback.
- [x] Confirm adapter parity for expression semantics, schema/dependency validation, operation order, sparse record reconstruction, stable sorting, global grouping/reductions, integer exactness, and cancellation-sensitive floating reductions.
- [x] Confirm origin alignment and source lifetime/consumption behavior through public queries across files, stdin, iterables, limits, sorting, and aggregation.
- [x] Run the unchanged core logging regression suite and inspect the diff to confirm emission behavior, root imports, compatibility shims, typed marker, and log-record schema remain intact.
- [x] Run Ruff, Pyrefly, diff checks, retained runnable examples, and installed-package/export checks. Verify retired transports, dependency extras, schemas, and obsolete tests are absent.
- [x] Inspect final ownership: query core, finite sources, and separate Python/Polars backends, without a miscellaneous helper pile or forwarding modules carrying old architecture.
- [x] Run representative small/large end-to-end benchmark cases with correctness digests, both adapters where supported, and origin-handling costs. Record implementation and dependency versions, timing, and memory where available; avoid brittle thresholds and unmeasured speedup claims.
- [x] Finish the maintained-documentation/link audit and clearly label any retained historical baseline evidence.
- [x] Resolve discovered regressions and record final validation and any explicit limitations. Do not claim migration completion until every implementation ticket is resolved.

## Implementation guidance

Ticket 05 transitively gates all earlier tickets, so no redundant direct blocking edges are required. This is the final integration/release verification slice, not a substitute for each ticket's own meaningful tests. New features, specialized-tool replacements, public plugins, and core logging changes remain out of scope.

## Resolution

Integrated baseline 4b777b0 contains tickets 01–05. Verified the full retained
suite through installed editable packages on Python 3.10.20/Polars 1.29.0 and
Python 3.13.9/Polars 1.44.2: 319 passed each. Ruff passed; Pyrefly reported zero
errors (33 suppressed). Query demos ran in base and native environments; six
retained logging demos completed. Built wheel contents and actual no-dependency
wheel installation were verified, including core typed/schema data, logging
compatibility, separate origins, ordinary application _id, and dependency_missing
for explicit Polars selection. Core implementation/root exports remain unchanged
apart from the authorized tooling docstring/entry-point/schema removals.

Published the complete version-2 benchmark matrix with revision/dependency
metadata: 16 cases at 200/100,000 rows, both adapters, three repeats, matching
record/origin digests and source-origin assertions. README documents medians,
RSS, and limits without speed claims. Maintained documentation/import and relative
file-link audits passed; historical evidence is identified. No code regression
was discovered, so no redundant implementation-mirroring tests were added.

Detailed evidence and explicit limits are in
[the verification report](../../../docs/reviews/ixr-only-verification.md).
All six implementation tickets are resolved and spec/tracker state is current.
Standards/Spec code review is intentionally not claimed by this resolution.
