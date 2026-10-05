# 08: Read long console messages comfortably

**What to build:** Console navigation remains useful with long messages,
wide custom fields, narrow terminals, and real variable-height wrapping.

**Blocked by:** 06

**Status:** resolved

Type: task

Source: [Native IXR investigation TUI specification](../spec.md). This is a production slice of the approved native design; resolved prototype work is evidence, not its implementation.

- [x] Wrap/pan controls preserve complete content and record selection; no fixed
  three-line or character preview limit replaces the original message.
- [x] Vertical/horizontal keyboard routes and available mouse scrolling work
  alongside paging, with stable aligned columns and narrow-layout focus routes.
- [x] Session controls expose time-only, date-and-time, original timestamp, and
  optional duration display. Full original field values remain inspectable.
- [x] Rendering/cache memory stays bounded under the declared admitted-record
  envelope, including resize and repeated navigation.
- [x] Keep reusable operations headless and explicitly scoped, with structured records, separate origins/status/diagnostics, bounded working storage, and unchanged IXR primitive semantics. TUI workflow and presentation state stay in the consumer; CLI/MCP transports remain outside this ticket.
- [x] Add behavior tests through Investigation session operations using real JSONL inputs and an installed package, plus focused native interaction tests where applicable. Cover this slice's errors, cleanup, and stale-result behavior where relevant; do not replace complete operations with previews.
- [x] Update current documentation and the changelog for public behavior, and run the appropriate shared development checks. Preserve optional dependencies, logging/schema compatibility, and Python 3.10/3.13 endpoint contracts when typing or attribution changes.

## Coordination

Owns ConsoleViewport navigation, wrapping and row mapping plus tui/presentation.py timestamp/duration/layout options. Presentation/session preferences remain in the consumer. Ticket07 alone changes headless capture contracts; ticket 09 owns JSONInspector and pane controls.

Shared app.py edits are owned by the behavior/class above. Compose, selection
handlers and bindings overlap: preserve all three slices at integration. Shared
native tests, documentation and imports are reconciled by the merger agents.
File overlap adds no semantic blocking edges. Detailed ownership notes:
`/private/tmp/slogger-tui-implementation/frontier-coordination.md`.

Integration baseline: `04c667d` on `codex/ixr-native-tui`.
Isolated worktree: `/Users/omkar.kabadagi/.codex/worktrees/tui-08/slogger`.
Verified editable Python3.13: `/private/tmp/slogger-tui-08-env/bin/python`.
Verified editable Python 3.10: `/private/tmp/slogger-tui-08-py310/bin/python`.
Both endpoint preflights passed before dispatch. Merge the latest integration
branch before reporting the ticket complete.


## Resolution

Implemented complete-content ConsoleViewport navigation in `tui/console.py`,
re-exported through the existing app interface. Record-and-line anchors map real
variable-height wrapping and hard newlines without a dataset-wide row-height
scan. Up/down select records; paging and Ctrl+Up/Down traverse display rows;
Home/End, mouse wheel/click, horizontal cell/page/reset routes and resize retain
stable original record selection. No fixed message or wrapped-line preview cap
is used. The viewport retains one admitted record layout, at most 1025 sparse
line checkpoints and visible strips only.

Added frozen consumer `ConsoleOptions` and complete original `console_fields`
values for subsequent settings/search integration. Focused W/T/D controls expose
wrap/pan, UTC time-only, UTC date-and-time, original timestamp and optional
`duration_ms`; option state is visible in the console heading. Aligned timestamp,
level and capped logger columns preserve full original inspection. Headless
Investigation records, resource contracts and IXR semantics are unchanged.
`capture_updated()` supports ticket 07's progressive prefix refresh without
resetting vertical record/line anchors. Ticket09's inspector ownership and
selected/Selected.ordinal interfaces remain compatible.

Merged integration `06f8d03` before implementation and `3e207f4` before resolution.
Installed editable CPython 3.13.9 and 3.10.20 shared checks passed: docs, Ruff,
Pyrefly and 340 tests on each endpoint, including focused real-JSONL native
wrapping, complete-tail paging, continuation selection, resize, timestamp/duration,
alignment, wide emoji custom-field panning and mouse scroll checks. Python 3.10's
first run reported a sandbox-only pytest cache-write warning; validation itself
passed. The final authorized check writes that cache normally.

Focused allocation probe: 40 records of 200,007 message characters in an 8,000,910-byte
source, three full navigation sweeps plus resize, a 32 KiB headless cache budget,
3.32/3.39/3.45 MB traced retained allocations, 4.87 MB traced peak and 54,771 bytes
last-sweep growth. This is a small bounded-workflow observation, not a measured
RSS or 1–5 GB capacity guarantee. Actual terminal/SSH/gesture behavior remains
unverified and belongs to ticket 23. Current user/architecture documentation and
the changelog were updated.

Interface/check notes and probe/log artifacts:
`/private/tmp/slogger-tui-implementation/ticket08-notes.md`.
