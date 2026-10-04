# 19: Detach and reattach aggregate filters with completion

**What to build:** An aggregate can copy the currently applied Main filter
into an independent editor, refine it with full completion, and explicitly reattach.

**Blocked by:** 12, 16

**Status:** claimed

Type: task

Source: [Native IXR investigation TUI specification](../spec.md). This is a production slice of the approved native design; resolved prototype work is evidence, not its implementation.

- [ ] Both editors share syntax, key/value discovery, typed insertion, keyboard,
  and mouse interaction. Detachment copies applied rather than draft text.
- [ ] Detached scopes survive subsequent main changes without changing the main
  view; reattachment resumes following the latest applied Main filter.
- [ ] Scope generations, selected-field presence, retained-result labels, errors,
  and cancellation work consistently for all available aggregate metrics.
- [ ] Numeric/grouped metrics and detachment can evolve concurrently through the
  same explicit operation scope; dependencies do not impose a false sequence.
- [ ] Keep reusable operations headless and explicitly scoped, with structured records, separate origins/status/diagnostics, bounded working storage, and unchanged IXR primitive semantics. TUI workflow and presentation state stay in the consumer; CLI/MCP transports remain outside this ticket.
- [ ] Add behavior tests through Investigation session operations using real JSONL inputs and an installed package, plus focused native interaction tests where applicable. Cover this slice's errors, cleanup, and stale-result behavior where relevant; do not replace complete operations with previews.
- [ ] Update current documentation and the changelog for public behavior, and run the appropriate shared development checks. Preserve optional dependencies, logging/schema compatibility, and Python 3.10/3.13 endpoint contracts when typing or attribution changes.

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
