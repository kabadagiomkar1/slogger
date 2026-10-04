# 19: Detach and reattach aggregate filters with completion

**What to build:** An aggregate can copy the currently applied Main filter
into an independent editor, refine it with full completion, and explicitly reattach.

**Blocked by:** 12, 16

**Status:** resolved

Type: task

Source: [Native IXR investigation TUI specification](../spec.md). This is a production slice of the approved native design; resolved prototype work is evidence, not its implementation.

- [x] Both editors share syntax, key/value discovery, typed insertion, keyboard,
  and mouse interaction. Detachment copies applied rather than draft text.
- [x] Detached scopes survive subsequent main changes without changing the main
  view; reattachment resumes following the latest applied Main filter.
- [x] Scope generations, selected-field presence, retained-result labels, errors,
  and cancellation work consistently for all available aggregate metrics.
- [x] Numeric/grouped metrics and detachment can evolve concurrently through the
  same explicit operation scope; dependencies do not impose a false sequence.
- [x] Keep reusable operations headless and explicitly scoped, with structured records, separate origins/status/diagnostics, bounded working storage, and unchanged IXR primitive semantics. TUI workflow and presentation state stay in the consumer; CLI/MCP transports remain outside this ticket.
- [x] Add behavior tests through Investigation session operations using real JSONL inputs and an installed package, plus focused native interaction tests where applicable. Cover this slice's errors, cleanup, and stale-result behavior where relevant; do not replace complete operations with previews.
- [x] Update current documentation and the changelog for public behavior, and run the appropriate shared development checks. Preserve optional dependencies, logging/schema compatibility, and Python 3.10/3.13 endpoint contracts when typing or attribution changes.

## Coordination

Ticket19 owns the native aggregate follow/detach/reattach state and independent
FilterEditor, sharing12's whole-dataset discovery index. Detachment copies applied
Main text rather than a pending draft. Headless scopes stay explicit; preserve16's
presence rule and leases,17's concurrent numeric metrics/replay, and18's later
grouped extension. Keep scope generation and retained-result labels coherent for
all metrics; changing Main must not invalidate a detached input scope.

17 owns numeric reducers/metric editing;21 owns settings, live resource updates,
themes and bounded tree wrapping.15 later owns filtered ancestor context. Preserve
search13, completion12 request/menu guards and shutdown cancellation. F5/F6 are
aggregate field/results, F7/F8 search, F9 metrics, F10 settings; Ctrl+R is reserved
for22 refresh. The merger reconciles aggregate/app composition, imports, shared
scope contracts, docs and combined native tests. Shared files add no blocker.

Claimed against clean integration `83126cd`, with12/16 resolved. Worktree
`codex/tui-19`: `/Users/omkar.kabadagi/.codex/worktrees/tui-19/slogger`, prepared
at `c8d1001`; merge current integration before work. Verified own editable
interpreters: `/private/tmp/slogger-tui-19-env/bin/python` (3.13, registered) and
`/private/tmp/slogger-tui-19-py310/bin/python` (3.10), actual Polars/Textual present.
Reuse without reinstalling or repointing primary. Notes under
`/private/tmp/slogger-tui-implementation/`: context.md, ticket12-notes.md,
ticket16-notes.md, execution-notes.md and refresh-coordination-notes.md. Coordinate
directly with17 on active metrics and21 on consumer composition.

## Resolution

Implemented native aggregate follow/detach/reattach policy in `codex/tui-19`,
composed with numeric metrics, exact nested/multiple grouping, completion, search,
and settings. Ctrl+D, compact pane controls, and command-palette actions expose
the independent Scope editor. It copies Main's successfully applied expression,
shares the complete discovery index, and materializes a separate explicitly leased
RecordView. Main changes leave the independent population intact; reattachment
uses the latest successfully applied Main. Scope changes retain requested metrics,
exact grouping bindings, and newer unsubmitted editor drafts.

Consumer mode, actual session ownership, editor generations, and immutable queued
field/metric/grouping snapshots guard publication. Errors, supersession,
cancellation, and failed initial detach retain honest prior-result labels without
falling back to all records. Selected-field presence remains mandatory, original
records remain unchanged, and derived origins remain separate. Existing headless
operations, IXR primitives, resource admission, and shutdown ownership are reused.
The narrow JSON route returns to the visible Scope editor, and narrow grouped F6
results retain a visible result row.

A real filter-monitor race surfaced during endpoint checks: a worker could publish
and exit between the empty pipe observation and exit check. Correction `82760f0`
rechecks queued frames after exit; a deterministic regression delays only the OS
IPC observation around the real subprocess. This repairs Main and independent
filter completion without increasing test timeouts or changing the protocol.

Nine new tests use installed-package real JSONL operations and focused native
interaction. Full shared documentation/Ruff/Pyrefly/pytest checks passed at
`82760f0`: **475 tests each on Python 3.13 and 3.10**. After adopting integrated
18 at `72989ea`, final source `e580e6c` passed shared fast checks and **43 combined
headless/native tests on each endpoint**, covering grouping, independent scopes,
completion, Main filtering, tree interaction, leases, drafts, and narrow results.
No final combined full-suite rerun is claimed; 18's separate full 479-test endpoint
evidence and these focused merged checks cover its composition.

Current public documentation and changelog are updated. Interpreters were reused
without installing or repointing dependencies. Actual terminal/SSH and large-data
performance qualification remain tickets 23/24. Interface, controlled-race diagnosis,
revision-specific logs, and final evidence are recorded in
`/private/tmp/slogger-tui-implementation/ticket19-notes.md`.
