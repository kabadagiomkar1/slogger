# 17: Summarize numeric fields exactly

**What to build:** Selecting a numeric field returns count, sum, mean,
minimum, and maximum for the complete present-field scope.

**Blocked by:** 16

**Status:** claimed

Type: task

Source: [Native IXR investigation TUI specification](../spec.md). This is a production slice of the approved native design; resolved prototype work is evidence, not its implementation.

- [ ] Numeric null behavior, incompatible false/non-numeric/nonfinite values,
  empty scopes, exact large integers, and compensated floating reductions
  agree with the reference. Count includes present null rows as specified.
- [ ] Bounded/spill reduction avoids naive batch-sum or batch-mean shortcuts;
  cancellation, errors, and cleanup preserve the last successful pane.
- [ ] Nested numeric paths and literal keys work without injecting application
  fields. Metric selection is editable and errors give useful type guidance.
- [ ] Keep reusable operations headless and explicitly scoped, with structured records, separate origins/status/diagnostics, bounded working storage, and unchanged IXR primitive semantics. TUI workflow and presentation state stay in the consumer; CLI/MCP transports remain outside this ticket.
- [ ] Add behavior tests through Investigation session operations using real JSONL inputs and an installed package, plus focused native interaction tests where applicable. Cover this slice's errors, cleanup, and stale-result behavior where relevant; do not replace complete operations with previews.
- [ ] Update current documentation and the changelog for public behavior, and run the appropriate shared development checks. Preserve optional dependencies, logging/schema compatibility, and Python 3.10/3.13 endpoint contracts when typing or attribution changes.

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
