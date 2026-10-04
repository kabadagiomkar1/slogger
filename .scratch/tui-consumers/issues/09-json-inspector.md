# 09: Inspect and compare complete JSON records

**What to build:** The right pane is independently navigable, resizeable,
toggleable, and pinnable, with complete record inspection and usable key targets.

**Blocked by:** 06

**Status:** claimed

Type: task

Source: [Native IXR investigation TUI specification](../spec.md). This is a production slice of the approved native design; resolved prototype work is evidence, not its implementation.

- [ ] Navigate long prettified JSON vertically/horizontally without a character
  preview cap; expose optional line numbers and retain valid-record indication.
- [ ] Hide/resize and pin/unpin have keyboard equivalents; selection and pinned
  inspection are distinct and source identity is visible.
- [ ] JSON key navigation exposes unambiguous nested/literal field targets for later
  field actions. Copy uses supported terminal capabilities or reports that it
  is unavailable; copied content is complete.
- [ ] Narrow resize and focus changes do not strand controls or discard a pin.
- [ ] Keep reusable operations headless and explicitly scoped, with structured records, separate origins/status/diagnostics, bounded working storage, and unchanged IXR primitive semantics. TUI workflow and presentation state stay in the consumer; CLI/MCP transports remain outside this ticket.
- [ ] Add behavior tests through Investigation session operations using real JSONL inputs and an installed package, plus focused native interaction tests where applicable. Cover this slice's errors, cleanup, and stale-result behavior where relevant; do not replace complete operations with previews.
- [ ] Update current documentation and the changelog for public behavior, and run the appropriate shared development checks. Preserve optional dependencies, logging/schema compatibility, and Python 3.10/3.13 endpoint contracts when typing or attribution changes.

## Coordination

Owns JSONInspector, nested/literal key targeting, pin/copy/resize/hide/focus controls. Preserve source identity and selected record independently of the pin. Key targets use IXR-compatible tuples of exact path components for later shared field operations; empty components unsupported by IXR need explicit guidance rather than coercion. Ticket08 owns ConsoleViewport/presentation, ticket07 owns capture contracts.

Shared app.py edits are owned by the behavior/class above. Compose, selection
handlers and bindings overlap: preserve all three slices at integration. Shared
native tests, documentation and imports are reconciled by the merger agents.
File overlap adds no semantic blocking edges. Detailed ownership notes:
`/private/tmp/slogger-tui-implementation/frontier-coordination.md`.

Integration baseline: `04c667d` on `codex/ixr-native-tui`.
Isolated worktree: `/Users/omkar.kabadagi/.codex/worktrees/tui-09/slogger`.
Verified editable Python3.13: `/private/tmp/slogger-tui-09-env/bin/python`.
Verified editable Python3.10: `/private/tmp/slogger-tui-09-py310/bin/python`.
Both endpoint preflights passed before dispatch. Merge the latest integration
branch before reporting the ticket complete.
