# 11: Complete filter syntax while editing

**What to build:** Contextual syntax choices help build a valid filter through
operators, functions, connectors, parentheses, and appropriately typed operands.

**Blocked by:** 10

**Status:** claimed

Type: task

Source: [Native IXR investigation TUI specification](../spec.md). This is a production slice of the approved native design; resolved prototype work is evidence, not its implementation.

- [ ] Keyboard up/down/Tab, mouse acceptance, dismissal, and continued editing work
  without overwriting a newer draft or prefix.
- [ ] Completion respects parsed context and supplies useful repair guidance.
  The editor interaction is reusable by the later independent aggregate editor.
- [ ] This slice completes syntax; 12 adds whole-dataset keys and observed values.
- [ ] Keep reusable operations headless and explicitly scoped, with structured records, separate origins/status/diagnostics, bounded working storage, and unchanged IXR primitive semantics. TUI workflow and presentation state stay in the consumer; CLI/MCP transports remain outside this ticket.
- [ ] Add behavior tests through Investigation session operations using real JSONL inputs and an installed package, plus focused native interaction tests where applicable. Cover this slice's errors, cleanup, and stale-result behavior where relevant; do not replace complete operations with previews.
- [ ] Update current documentation and the changelog for public behavior, and run the appropriate shared development checks. Preserve optional dependencies, logging/schema compatibility, and Python 3.10/3.13 endpoint contracts when typing or attribution changes.

## Coordination

Ticket11 owns contextual syntax completion and reusable native completion-menu
interaction in `tools/core/filter_language.py` (shared grammar context) and
`tools/tui/filter_editor.py`. Preserve10 parser/scopes/lifecycle and09 focus/palette
routing.13 owns search/highlight changes to console/app;16 owns field targeting and
aggregate pane/app.14 owns trace reconstruction/native tree.20 owns durable storage,
leases and admission; do not replace their contracts. Prefer additive app hooks and
separate feature modules. The merger reconciles shared imports, app composition,
styles, documentation and combined native tests; no overlap adds semantic blockers.

Claimed against integration `f8b26db` after10 resolved. Worktree `codex/tui-11`:
`/Users/omkar.kabadagi/.codex/worktrees/tui-11/slogger`; prepared at `ee7cfc8`,
merge current integration before work. Verified editable interpreters:
`/private/tmp/slogger-tui-11-env/bin/python` (3.13, registered) and
`/private/tmp/slogger-tui-11-py310/bin/python` (3.10). Both include actual
Polars/Textual. Reuse them; do not reinstall or repoint the primary environments.
