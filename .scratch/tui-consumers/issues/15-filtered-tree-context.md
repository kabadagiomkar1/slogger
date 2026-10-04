# 15: Filter and search through ancestor context

**What to build:** Tree mode honors the applied filter while retaining marked
ancestors, and search reveals matching records through folded paths.

**Blocked by:** 13, 14

**Status:** claimed

Type: task

Source: [Native IXR investigation TUI specification](../spec.md). This is a production slice of the approved native design; resolved prototype work is evidence, not its implementation.

- [ ] Ancestor context explains matches but is not itself a filter/search match or
  aggregate contributor merely because it is displayed.
- [ ] Search next/previous reveals required ancestors and keeps source-order
  navigation and flat/tree selection coherent.
- [ ] Filter/search generation changes cannot publish stale tree membership or
  context; uncertainty remains honestly represented.
- [ ] Keep reusable operations headless and explicitly scoped, with structured records, separate origins/status/diagnostics, bounded working storage, and unchanged IXR primitive semantics. TUI workflow and presentation state stay in the consumer; CLI/MCP transports remain outside this ticket.
- [ ] Add behavior tests through Investigation session operations using real JSONL inputs and an installed package, plus focused native interaction tests where applicable. Cover this slice's errors, cleanup, and stale-result behavior where relevant; do not replace complete operations with previews.
- [ ] Update current documentation and the changelog for public behavior, and run the appropriate shared development checks. Preserve optional dependencies, logging/schema compatibility, and Python 3.10/3.13 endpoint contracts when typing or attribution changes.

## Coordination

Ticket15 owns explicit filtered-tree membership and marked ancestor context,
search reveal through folded paths, and coherent flat/tree selection. Preserve
14's complete immutable trace evidence, first-appearance ordering and uncertainty;
displayed context is not a query/search match or aggregate contributor.13 owns
semantic search membership/projection and native highlight/navigation controls.
Use scoped result handles, leases and consumer generations to reject stale work.

21 concurrently owns bounded tree wrapped-row handling and palette themes;
coordinate tree viewport additions directly and preserve its wrap behavior.
17/18 own aggregate reductions/grouping,19 owns detached scope/editor state.
Keep Main result membership authoritative and avoid coupling aggregate input to
display context.22 later owns atomic replacement. The merger reconciles tree,
app/controller interfaces, imports, docs and combined search/filter/tree tests.
File overlap does not add semantic blockers. Existing key bindings remain intact.

Claimed against clean integration `eaab141`, with13/14 resolved. Worktree
`codex/tui-15`: `/Users/omkar.kabadagi/.codex/worktrees/tui-15/slogger`, prepared
at `c8d1001`; merge latest integration before work. Verified own editable
interpreters: `/private/tmp/slogger-tui-15-env/bin/python` (3.13, registered) and
`/private/tmp/slogger-tui-15-py310/bin/python` (3.10), actual Polars/Textual present.
Reuse without reinstalling or repointing primary. Notes under
`/private/tmp/slogger-tui-implementation/`: context.md, ticket13-notes.md,
ticket14-notes.md, ticket20-notes.md and refresh-coordination-notes.md. Dispatch
when a concurrency slot is available; latest21 notes describe viewport wrapping.
