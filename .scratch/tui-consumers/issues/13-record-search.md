# 13: Search filtered records with live highlighting

**What to build:** Literal text search highlights as the user types and
navigates matching records inside the applied Main filter without filtering them.

**Blocked by:** 10

**Status:** claimed

Type: task

Source: [Native IXR investigation TUI specification](../spec.md). This is a production slice of the approved native design; resolved prototype work is evidence, not its implementation.

- [ ] Console/full-record scopes use complete decoded names/values, including
  hidden metadata in full scope; serialization escapes do not become matches.
- [ ] Case and Unicode whole-word options, immediate highlights, no typing-driven
  cursor movement, complete background record counts, and next/previous/wrap
  navigation are usable with clear option states.
- [ ] Changing scope, case, word options, or console-field visibility recomputes
  visible highlights and the complete match set, superseding prior work.
- [ ] Empty search clears matches. Filter/request changes invalidate stale match
  scopes; cancellation and pending status preserve the prior successful view.
- [ ] The complete match index is paged/disk-backed and resource-accounted.
- [ ] Keep reusable operations headless and explicitly scoped, with structured records, separate origins/status/diagnostics, bounded working storage, and unchanged IXR primitive semantics. TUI workflow and presentation state stay in the consumer; CLI/MCP transports remain outside this ticket.
- [ ] Add behavior tests through Investigation session operations using real JSONL inputs and an installed package, plus focused native interaction tests where applicable. Cover this slice's errors, cleanup, and stale-result behavior where relevant; do not replace complete operations with previews.
- [ ] Update current documentation and the changelog for public behavior, and run the appropriate shared development checks. Preserve optional dependencies, logging/schema compatibility, and Python 3.10/3.13 endpoint contracts when typing or attribution changes.

## Coordination

Ticket13 owns headless decoded literal-text matching and bounded complete match
indexes, plus native compact search controls, console highlighting, navigation
and search-generation app hooks. Headless search receives explicit projection
options for the console field set; it must not import Textual/Rich or native
consumer defaults.11 owns reusable FilterEditor/menu/context;16 owns console/JSON
field targets and the lower aggregate pane;14 owns native/headless trees;15 later
joins search/filter results with ancestor context.20 owns durable global storage,
leases and admission. Preserve10 scopes, input leases and session-close registry.

Prefer feature modules and additive console/app hooks. The merger reconciles
shared imports, rendering/CSS, docs/changelog and combined interaction tests;
file overlap introduces no additional semantic blocker.

Claimed against integration `f3fc4d8` after10 resolved. Worktree `codex/tui-13`:
`/Users/omkar.kabadagi/.codex/worktrees/tui-13/slogger`; prepared at `ee7cfc8`,
merge latest integration before work. Verified editable endpoint environments:
`/private/tmp/slogger-tui-13-env/bin/python` (3.13, registered) and
`/private/tmp/slogger-tui-13-py310/bin/python` (3.10), with actual Polars/Textual.
Reuse them; do not reinstall or repoint primary. Pointers outside repository:
`/private/tmp/slogger-tui-implementation/context.md`, `execution-notes.md`,
`filter-search-aggregate-coordination.md` and `ticket08/10/14-notes.md`.
