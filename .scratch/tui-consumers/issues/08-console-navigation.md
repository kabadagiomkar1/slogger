# 08: Read long console messages comfortably

**What to build:** Console navigation remains useful with long messages,
wide custom fields, narrow terminals, and real variable-height wrapping.

**Blocked by:** 06

**Status:** claimed

Type: task

Source: [Native IXR investigation TUI specification](../spec.md). This is a production slice of the approved native design; resolved prototype work is evidence, not its implementation.

- [ ] Wrap/pan controls preserve complete content and record selection; no fixed
  three-line or character preview limit replaces the original message.
- [ ] Vertical/horizontal keyboard routes and available mouse scrolling work
  alongside paging, with stable aligned columns and narrow-layout focus routes.
- [ ] Session controls expose time-only, date-and-time, original timestamp, and
  optional duration display. Full original field values remain inspectable.
- [ ] Rendering/cache memory stays bounded under the declared admitted-record
  envelope, including resize and repeated navigation.
- [ ] Keep reusable operations headless and explicitly scoped, with structured records, separate origins/status/diagnostics, bounded working storage, and unchanged IXR primitive semantics. TUI workflow and presentation state stay in the consumer; CLI/MCP transports remain outside this ticket.
- [ ] Add behavior tests through Investigation session operations using real JSONL inputs and an installed package, plus focused native interaction tests where applicable. Cover this slice's errors, cleanup, and stale-result behavior where relevant; do not replace complete operations with previews.
- [ ] Update current documentation and the changelog for public behavior, and run the appropriate shared development checks. Preserve optional dependencies, logging/schema compatibility, and Python 3.10/3.13 endpoint contracts when typing or attribution changes.

## Coordination

Owns ConsoleViewport navigation, wrapping and row mapping plus tui/presentation.py timestamp/duration/layout options. Presentation/session preferences remain in the consumer. Ticket07 alone changes headless capture contracts; ticket09 owns JSONInspector and pane controls.

Shared app.py edits are owned by the behavior/class above. Compose, selection
handlers and bindings overlap: preserve all three slices at integration. Shared
native tests, documentation and imports are reconciled by the merger agents.
File overlap adds no semantic blocking edges. Detailed ownership notes:
`/private/tmp/slogger-tui-implementation/frontier-coordination.md`.

Integration baseline: `04c667d` on `codex/ixr-native-tui`.
Isolated worktree: `/Users/omkar.kabadagi/.codex/worktrees/tui-08/slogger`.
Verified editable Python3.13: `/private/tmp/slogger-tui-08-env/bin/python`.
Verified editable Python3.10: `/private/tmp/slogger-tui-08-py310/bin/python`.
Both endpoint preflights passed before dispatch. Merge the latest integration
branch before reporting the ticket complete.
