# 07: Browse progressive capture and recover from opening failures

**What to build:** A large investigation becomes browseable during capture,
with honest progress, safe cancellation, and retained partial records on failure.

**Blocked by:** 06

**Status:** resolved

Type: task

Source: [Native IXR investigation TUI specification](../spec.md). This is a production slice of the approved native design; resolved prototype work is evidence, not its implementation.

- [x] Background capture permits console selection and JSON inspection of the
  captured prefix; the shared readiness contract keeps all dataset-wide
  operations unavailable until complete, including operations added by other slices.
- [x] Failed/canceled opening retains already captured records until session close,
  marked incomplete, with actionable diagnostics and no reusable-complete flag.
- [x] Observed source truncation/replacement/mutation, file access failures, disk
  exhaustion, and declared oversized-record limits cannot silently omit data.
- [x] Closing/canceling releases owned resources and superseded capture work cannot
  publish into a newer investigation.
- [x] Keep reusable operations headless and explicitly scoped, with structured records, separate origins/status/diagnostics, bounded working storage, and unchanged IXR primitive semantics. TUI workflow and presentation state stay in the consumer; CLI/MCP transports remain outside this ticket.
- [x] Add behavior tests through Investigation session operations using real JSONL inputs and an installed package, plus focused native interaction tests where applicable. Cover this slice's errors, cleanup, and stale-result behavior where relevant; do not replace complete operations with previews.
- [x] Update current documentation and the changelog for public behavior, and run the appropriate shared development checks. Preserve optional dependencies, logging/schema compatibility, and Python 3.10/3.13 endpoint contracts when typing or attribution changes.

## Coordination

Owns capture orchestration in investigation/session.py and capture.py, CaptureStatus progress/cancel extensions, bounded writers/admission in resources.py, and native loading/progress wiring. Preserve page/identity/readiness contracts. Read the measured capture-cost notes; repair repeated per-record filesystem scans while retaining exact budget admission and atomic data/index prefix publication. Ticket20 extends this storage contract to durable cache ownership later.

Shared app.py edits are owned by the behavior/class above. Compose, selection
handlers and bindings overlap: preserve all three slices at integration. Shared
native tests, documentation and imports are reconciled by the merger agents.
File overlap adds no semantic blocking edges. Detailed ownership notes:
`/private/tmp/slogger-tui-implementation/frontier-coordination.md`.

Integration baseline: `04c667d` on `codex/ixr-native-tui`.
Isolated worktree: `/Users/omkar.kabadagi/.codex/worktrees/tui-07/slogger`.
Verified editable Python3.13: `/private/tmp/slogger-tui-07-env/bin/python`.
Verified editable Python3.10: `/private/tmp/slogger-tui-07-py310/bin/python`.
Both endpoint preflights passed before dispatch. Merge the latest integration
branch before reporting the ticket complete.


## Resolution

Implemented progressive `Investigation.open(..., background=True)` with opening
boundaries established before return, structured capturing/verifying/canceled
states, verified-byte progress, cooperative cancel, bounded wait, and close/join
cleanup. Pages and complete JSON inspection retain a published incomplete prefix;
all complete-dataset operations still pass `require_ready`, including future
operations and final content verification. Source mutation/replacement/truncation,
access/decode/admission failures, and partial disk writes remain explicit errors.

Capture and diagnostics use bounded paired batches, persistent managed handles,
block-growth reservations, changed-file allocation checks, and whole-batch rollback
before publishing aligned counts. Native loading exposes progress and error
origins, retains inspection on failure/cancel, and binds Esc to cancellation.
Current guides, architecture/capability documentation, and changelog were updated.

TDD and regression validation used installed real JSONL session operations and
focused Textual interaction. Shared docs/Ruff/Pyrefly/pytest passed on CPython3.13
and3.10:348tests on each endpoint before integration of the console slice.
The existing18.09MiB representative capture probe now opens in0.508/0.525seconds,
with all24000records,96skips, exact opening-byte counts, first/last pages, and
cleanup checked; earlier per-record bookkeeping took5.964/6.134seconds. This is
bounded small-fixture evidence, not1–5GB/terminal/SSH qualification. Full source
fingerprints, probe output, interfaces, and final integration/check evidence are
recorded in `/private/tmp/slogger-tui-implementation/ticket07-notes.md`.
