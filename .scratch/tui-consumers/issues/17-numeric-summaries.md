# 17: Summarize numeric fields exactly

**What to build:** Selecting a numeric field returns count, sum, mean,
minimum, and maximum for the complete present-field scope.

**Blocked by:** 16

**Status:** resolved

Type: task

Source: [Native IXR investigation TUI specification](../spec.md). This is a production slice of the approved native design; resolved prototype work is evidence, not its implementation.

- [x] Numeric null behavior, incompatible false/non-numeric/nonfinite values,
  empty scopes, exact large integers, and compensated floating reductions
  agree with the reference. Count includes present null rows as specified.
- [x] Bounded/spill reduction avoids naive batch-sum or batch-mean shortcuts;
  cancellation, errors, and cleanup preserve the last successful pane.
- [x] Nested numeric paths and literal keys work without injecting application
  fields. Metric selection is editable and errors give useful type guidance.
- [x] Keep reusable operations headless and explicitly scoped, with structured records, separate origins/status/diagnostics, bounded working storage, and unchanged IXR primitive semantics. TUI workflow and presentation state stay in the consumer; CLI/MCP transports remain outside this ticket.
- [x] Add behavior tests through Investigation session operations using real JSONL inputs and an installed package, plus focused native interaction tests where applicable. Cover this slice's errors, cleanup, and stale-result behavior where relevant; do not replace complete operations with previews.
- [x] Update current documentation and the changelog for public behavior, and run the appropriate shared development checks. Preserve optional dependencies, logging/schema compatibility, and Python 3.10/3.13 endpoint contracts when typing or attribution changes.

## Coordination

Ticket17 owns shared bounded numeric reduction/replay and editable numeric metrics
in the native aggregate pane. Preserve16 `FieldBinding`, selected presence,
`AggregateScope`/job/result paging, explicit input leases, type identity and
retained applied scope/drafts/visibility. Existing Python reference reduction
ordering, null counts, exact integers and compensated float errors remain the
semantic authority.18 later extends grouping through the same binding/reducer;
19 will own aggregate follow/detached scope linkage and independent FilterEditor.

12 owns discovery/editor choices;13 owns search/highlights;15 will own ancestor
context;21 will own preferences/runtime limit changes.20 owns managed global disk,
engine growth/sidecar admission and leases. Keep all shared primitives headless;
consumer metric defaults/editing stay native. The merger reconciles imports,
aggregate editor/app composition, docs and combined native behavior. Numeric and
independent scope work may proceed concurrently without false file blockers.

Claimed against integration `d8454d4`, with16 resolved. Worktree `codex/tui-17`:
`/Users/omkar.kabadagi/.codex/worktrees/tui-17/slogger`, prepared at `f3fc4d8`;
merge latest integration before work. Verified editable endpoint interpreters:
`/private/tmp/slogger-tui-17-env/bin/python` (3.13, registered) and
`/private/tmp/slogger-tui-17-py310/bin/python` (3.10), actual Polars/Textual present.
Reuse them without installs or primary repointing. Outside-repo pointers under
`/private/tmp/slogger-tui-implementation/`: context.md, execution-notes.md,
ticket16-notes.md, ticket20-notes.md and refresh-coordination-notes.md.

## Resolution

Added `Investigation.summarize_values` over explicit dataset/view scopes, with
ordered editable count/sum/mean/min/max metrics and the existing presence, job,
lease and paged-result contracts. Numeric validation and checked finalization
are shared with the Python reference. Complete validation precedes original-order
contribution replay; integer totals remain exact, floating sums use whole-sequence
`math.fsum`, null counts/reduction skips and first min/max ties retain reference
meaning. No subtotal or mean-of-means shortcut is used.

Managed fixed-width ordinal spools have bounded writer buffers and are reclaimed
before successful publication. Replay checks cancellation; failures independently
release handles and input leases, preserving original creation errors even when
cleanup also fails. Internal scalar encoding preserves exact integer results beyond
decimal conversion thresholds without changing interpreter settings or returned
records. Complete structured result counts agree with delivered summaries.

The native lower pane adds a compact Metrics row, F9 and palette focus. Observed
numeric values default to the full summary; `values` and ordered numeric metric
lists remain editable. Main following preserves metric choices, newer drafts and
hidden panes; pending, failed, canceled and superseded requests retain the prior
result's own scope. F7/F8 remain Record search and F5/F6 remain field/results.

Verified own installed editable Python3.13.9 and3.10.20 environments with actual
Polars/Textual, including integrated search13/discovery12. Full shared documentation,
Ruff, Pyrefly and pytest checks passed **459 tests on each endpoint** at `b597649`.
Adopted latest `76386cc` afterward: claim-only tracker changes, identical checked
implementation tree; final documentation/fast checks passed. Eight real-JSONL
headless tests and two focused native tests cover complete spill/replay, reference
type/overflow ordering, exact/empty/nested/null behavior, first ties, disk admission,
replay cancellation, construction/cleanup faults, metric editing and supersession.
An earlier concurrent-run native five-second wait timed out once; focused and full
reruns passed without a semantic difference. Test waits are not latency guarantees.

Focused traced-allocation evidence at `914b17b` compared3,000/30,000 contributions
with64KiB working admission and1KiB browsing cache: peaks37,060/30,717 traced bytes
and12,320 retained result disk bytes each, reclaimed on close. Probe code, hashes
and results are saved in the outside-repo ticket17 handoff notes. This excludes
SQLite/native/runtime/OS memory and does not establish RSS, terminal/SSH or1–5GB
qualification; tickets23/24 retain those obligations. Public API, native guide,
ownership/capability documentation and changelog are current.
