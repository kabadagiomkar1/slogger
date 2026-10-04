# 18: Group summaries by multiple and nested fields

**What to build:** The aggregate editor adds multiple grouping fields and
metrics, with exact paged summaries over nested or literal-key fields.

**Blocked by:** 17

**Status:** claimed

Type: task

Source: [Native IXR investigation TUI specification](../spec.md). This is a production slice of the approved native design; resolved prototype work is evidence, not its implementation.

- [ ] Extend/reuse collision-safe shared path binding, preserve literal top-level
  grouping compatibility, and leave source application records untouched.
- [ ] Secondary grouping keys preserve missing/null and typed numeric/bool rules;
  only the selected aggregate field receives the automatic presence guard.
- [ ] High-cardinality groups preserve first appearance and complete reductions
  with bounded working memory, disk admission, progress, and cancellation.
- [ ] Keep reusable operations headless and explicitly scoped, with structured records, separate origins/status/diagnostics, bounded working storage, and unchanged IXR primitive semantics. TUI workflow and presentation state stay in the consumer; CLI/MCP transports remain outside this ticket.
- [ ] Add behavior tests through Investigation session operations using real JSONL inputs and an installed package, plus focused native interaction tests where applicable. Cover this slice's errors, cleanup, and stale-result behavior where relevant; do not replace complete operations with previews.
- [ ] Update current documentation and the changelog for public behavior, and run the appropriate shared development checks. Preserve optional dependencies, logging/schema compatibility, and Python 3.10/3.13 endpoint contracts when typing or attribution changes.

## Coordination

Ticket18 owns collision-safe grouping bindings, complete indexed per-group numeric
replay/results and native grouping configuration. Reuse17's shared reference
validation/finalization and preserve source/configured-metric ordering, exact
integers, typed first representatives, missing versus null secondary keys and
16's selected-field presence guard. Public literal top-level QueryPlan grouping
contracts remain stable; nested bindings stay explicit and out of application data.

19 concurrently owns native aggregate follow/detach scope/editor state,21 owns
settings/resources/themes, and15 later owns filtered tree context. Coordinate
additive AggregateScope/request snapshots and consumer draft/result labels directly
with19; grouping and numeric metrics must work in every explicit input scope.
Preserve job/view leases, managed disk growth, cancellation/cleanup and shutdown
guards. F5/F6 field/results, F7/F8 search, F9 metrics, F10 settings and Ctrl+R
refresh remain reserved; grouping may use palette and normal focus navigation.
The merger reconciles shared aggregation/app contracts, imports, docs and combined
native behavior. Shared-file overlap adds no semantic blocker.

Claimed against clean integration `5209f56`, with17 resolved. Worktree
`codex/tui-18`: `/Users/omkar.kabadagi/.codex/worktrees/tui-18/slogger`, prepared
at `c8d1001`; merge latest integration before work. Verified own editable
interpreters: `/private/tmp/slogger-tui-18-env/bin/python` (3.13, registered) and
`/private/tmp/slogger-tui-18-py310/bin/python` (3.10), actual Polars/Textual present.
Reuse without reinstalling or repointing primary. Notes under
`/private/tmp/slogger-tui-implementation/`: context.md, ticket17-notes.md,
ticket16-notes.md, execution-notes.md and refresh-coordination-notes.md.19 is
`/root/implement_tui_19`; its latest branch/notes must be reconciled before done.
