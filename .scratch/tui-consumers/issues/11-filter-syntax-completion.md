# 11: Complete filter syntax while editing

**What to build:** Contextual syntax choices help build a valid filter through
operators, functions, connectors, parentheses, and appropriately typed operands.

**Blocked by:** 10

**Status:** resolved

Type: task

Source: [Native IXR investigation TUI specification](../spec.md). This is a production slice of the approved native design; resolved prototype work is evidence, not its implementation.

- [x] Keyboard up/down/Tab, mouse acceptance, dismissal, and continued editing work
  without overwriting a newer draft or prefix.
- [x] Completion respects parsed context and supplies useful repair guidance.
  The editor interaction is reusable by the later independent aggregate editor.
- [x] This slice completes syntax; 12 adds whole-dataset keys and observed values.
- [x] Keep reusable operations headless and explicitly scoped, with structured records, separate origins/status/diagnostics, bounded working storage, and unchanged IXR primitive semantics. TUI workflow and presentation state stay in the consumer; CLI/MCP transports remain outside this ticket.
- [x] Add behavior tests through Investigation session operations using real JSONL inputs and an installed package, plus focused native interaction tests where applicable. Cover this slice's errors, cleanup, and stale-result behavior where relevant; do not replace complete operations with previews.
- [x] Update current documentation and the changelog for public behavior, and run the appropriate shared development checks. Preserve optional dependencies, logging/schema compatibility, and Python 3.10/3.13 endpoint contracts when typing or attribution changes.

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


## Resolution

Implemented shared `complete_filter`, `FilterCompletion`, and `FilterChoice` in
query core. Completion follows the existing parser's grammar positions, with
field/operator and typed JSON context, functions, NOT/groups, AND/OR, function
argument separators, closing delimiters, and scalar membership-array choices.
It reads no dataset and imports no terminal dependency. Exact draft/cursor/
generation/replacement bounds prevent stale edits; escaped strings and complete
JSON numeric spans retain their intended context. Accepting an existing closer
advances across it without duplicating it.

The reusable native FilterEditor supplies a scrollable keyboard/mouse menu,
up/down and Tab acceptance, Escape dismissal, Ctrl+Space reopening, continued
editing, and contextual repair help beside the applied state. Each editor owns
its menu and draft state; no observed field/value index is introduced ahead of12.
Enter still applies IXR through the existing Investigation operation. Shared
parser/execution semantics, captured records, origins, pinned JSON, normal pane
focus, narrow layout and command-palette routing remain covered.

Verified the pre-provisioned editable endpoint interpreters against this worktree
without reinstalling or repointing another checkout. Merged integration0fbfbd0
before work and subsequent14/current claim tipc8d1001 before final checks.
Implementation commits7db2191 and502e004; final tested source tree1e66181.
Full `python3 scripts/dev.py check` passed documentation, Ruff, Pyrefly and
**398 tests** on CPython3.13.9 and3.10.20 with actual Polars1.44.2/Textual8.2.8.
Seven focused native tests open real JSONL Investigation inputs and cover actual
filter application and physical origins, syntax/typed templates, arrays and type
errors, suffixes, mouse/keyboard acceptance, dismissal/reopening, independent
editors, stale draft/cursor rejection, escaped/nested literal paths, narrow/palette
focus, decimals/exponents and closing-delimiter reuse. Observed failing behavior
before each new implementation slice; no internal collaborators are mocked.

Evidence/API pointers: `/private/tmp/slogger-tui-implementation/ticket11-notes.md`,
`ticket11-check-py313.log`, and `ticket11-check-py310.log` in that directory.
These are installed native headless tests, not actual emulator, SSH or scale
qualification; those remain their dedicated tickets.
