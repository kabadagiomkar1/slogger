# 09: Inspect and compare complete JSON records

**What to build:** The right pane is independently navigable, resizeable,
toggleable, and pinnable, with complete record inspection and usable key targets.

**Blocked by:** 06

**Status:** resolved

Type: task

Source: [Native IXR investigation TUI specification](../spec.md). This is a production slice of the approved native design; resolved prototype work is evidence, not its implementation.

- [x] Navigate long prettified JSON vertically/horizontally without a character
  preview cap; expose optional line numbers and retain valid-record indication.
- [x] Hide/resize and pin/unpin have keyboard equivalents; selection and pinned
  inspection are distinct and source identity is visible.
- [x] JSON key navigation exposes unambiguous nested/literal field targets for later
  field actions. Copy uses supported terminal capabilities or reports that it
  is unavailable; copied content is complete.
- [x] Narrow resize and focus changes do not strand controls or discard a pin.
- [x] Keep reusable operations headless and explicitly scoped, with structured records, separate origins/status/diagnostics, bounded working storage, and unchanged IXR primitive semantics. TUI workflow and presentation state stay in the consumer; CLI/MCP transports remain outside this ticket.
- [x] Add behavior tests through Investigation session operations using real JSONL inputs and an installed package, plus focused native interaction tests where applicable. Cover this slice's errors, cleanup, and stale-result behavior where relevant; do not replace complete operations with previews.
- [x] Update current documentation and the changelog for public behavior, and run the appropriate shared development checks. Preserve optional dependencies, logging/schema compatibility, and Python 3.10/3.13 endpoint contracts when typing or attribution changes.

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


## Resolution

Implemented complete virtual JSON scrolling and optional line numbers in
`src/slogger/tools/tui/inspector.py`, re-exported through the existing native app
module. Key navigation/clicks expose tuples of exact mapping-key components;
escaped bracket labels distinguish nested paths and dotted/space/quoted literal
keys. Empty components and keys inside array items retain their JSON content but
show explicit IXR targeting guidance. Enter emits the exact field request for
later aggregate integration; no IXR primitive or record data is changed.

The consumer retains selected and pinned identities/origins separately, shows
both compact source locations and input occurrences, and preserves a pin across
selection, hide/show, resizing and focus changes. I, brackets, P, C, F2/F3 and
Tab provide keyboard routes. A full-width inspector remains accessible below
90 columns; the command palette lists pane controls when the footer is clipped.
Copy sends the complete inspected/pinned document through Textual OSC 52 on a
native transport, reports acceptance as unverified, and clearly reports empty,
headless, known unsupported macOS Terminal, or failed transport states.

Integration baseline merged before final checks: `3e207f4`.
Verified installed editable environments: Python3.13
`/private/tmp/slogger-tui-09-env/bin/python` and Python3.10
`/private/tmp/slogger-tui-09-py310/bin/python`; actual Textual8.2.8 and Polars1.44.2.
Shared docs/Ruff/Pyrefly/pytest checks passed on both endpoints:344tests each.
The focused inspector suite has7tests through real JSONL Investigation sessions
and native run_test, including long Unicode documents, literal/nested keys,
unsupported guidance, repeated occurrences, pin/focus/resize/copy, empty/error
states, cleanup and a rendered selected/pinned-label regression. Terminal
transport alone is injected for deterministic copy/failure checks.

Current user guide and changelog updated. Coordination/interface/check notes:
`/private/tmp/slogger-tui-implementation/ticket09-notes.md`; endpoint logs are
`ticket09-check-py313.log` and `ticket09-check-py310.log` beside that file.
Actual terminal clipboard acceptance, gestures, SSH/multiplexer behavior, and
1–5GB scale are not established by these headless checks and remain in their
qualification tickets. No primary checkout or headless capture API edits.
