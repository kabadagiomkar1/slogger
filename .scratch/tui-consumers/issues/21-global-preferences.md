# 21: Save useful global preferences and themes

**What to build:** A keyboard-accessible settings view changes real presentation
and resource behavior, with coherent dark/light themes and explicit saved defaults.

**Blocked by:** 08, 09, 20

**Status:** resolved

Type: task

Source: [Native IXR investigation TUI specification](../spec.md). This is a production slice of the approved native design; resolved prototype work is evidence, not its implementation.

- [x] Theme, wrap, timestamp, duration, inspector line numbers, pane size/visibility,
  resource limits, expiry, usage, and protected clearing are usable options.
- [x] Session adjustments do not implicitly overwrite global defaults; saving is
  explicit. Query/search/navigation histories remain session-only.
- [x] Narrow layouts preserve access and both themes provide readable control,
  JSON, selection, error, and search-highlight states.
- [x] Keep reusable operations headless and explicitly scoped, with structured records, separate origins/status/diagnostics, bounded working storage, and unchanged IXR primitive semantics. TUI workflow and presentation state stay in the consumer; CLI/MCP transports remain outside this ticket.
- [x] Add behavior tests through Investigation session operations using real JSONL inputs and an installed package, plus focused native interaction tests where applicable. Cover this slice's errors, cleanup, and stale-result behavior where relevant; do not replace complete operations with previews.
- [x] Update current documentation and the changelog for public behavior, and run the appropriate shared development checks. Preserve optional dependencies, logging/schema compatibility, and Python 3.10/3.13 endpoint contracts when typing or attribution changes.

## Coordination

Ticket21 owns persisted native presentation defaults, usable settings/themes, and
an additive atomic headless runtime resource/expiry update API.20's final notes
explain active storage/cache owner coherence, admission validation and RAM eviction;
no runtime setter exists yet. Reject/defer unsafe decreases while preserving active
data and worker snapshots. Keep effective session values distinct from explicit
saved defaults.13 owns semantic highlights/search;17 owns numeric metrics;12 owns
completion discovery;19 later owns independent aggregate editor;15 owns context.

Coordinate native app/panes/styles additively, preserving pins, target metadata,
completion focus and shutdown guards. F5/F6 are aggregate field/results, F7/F8
search, F9 metrics; use F10 settings plus palette.22 may use Ctrl+R refresh. The
merger reconciles imports, shared resource contracts, defaults/launch composition,
themes/docs and native interaction checks. Shared files add no semantic blocker.

Claimed against integration `885b15e`, with08/09/20 resolved and13 integrated.
Worktree `codex/tui-21`: `/Users/omkar.kabadagi/.codex/worktrees/tui-21/slogger`,
prepared at `0fbfbd0`; merge current integration before work. Verified own editable
interpreters: `/private/tmp/slogger-tui-21-env/bin/python` (3.13, registered) and
`/private/tmp/slogger-tui-21-py310/bin/python` (3.10), actual Polars/Textual present.
Reuse without reinstalling or repointing primary. Pointers under
`/private/tmp/slogger-tui-implementation/`: context.md, ticket20-notes.md,
preferences-coordination-notes.md and refresh-coordination-notes.md. Tests use
explicit temporary settings/cache locations; no import-time user writes/history.


## Resolution

Implemented compact F10/palette settings with keyboard access to real presentation,
resource budgets, expiry, usage and protected clear. Applying changes is temporary;
Ctrl+S explicitly atomically saves current applied defaults. The native launcher
loads defaults and composes matching command-line overrides. Neither path selection,
import nor missing-default load writes files; preferences exclude queries, searches,
pins and navigation. Real dark/light palettes preserve syntax, field metadata and
live highlighting. JSON strips now remove the syntax lexer's generated newline and
use the pane background, fixing visual gaps. Tree records use bounded sparse layouts
and visible continuation strips with wrapped paging, retaining folds/selection/pins.

Added `Investigation.configure_resources()` and immutable `ResourceConfiguration`.
It validates capture admission, actual/reserved disk, finite expiry and unsafe memory
decreases before publishing coherent session/storage/cache-owner values. Execution
snapshots remain protected until capture/jobs/results settle/close; encoded RAM
shrinks immediately. RAM/expiry changes remain possible if another opener has raised
shared usage under a larger budget. Future admissions use effective values. Added
settled `done` lifecycle properties to tree/discovery jobs for shared safety gating.

Based on99f19c7 and merged latest integration throughdd91a4d before completion,
including12 discovery and17 numeric metrics. Full shared docs/Ruff/Pyrefly/pytest
checks passed **467 tests on each Python3.13/3.10 endpoint at598f66b**. Following the
final three-line JSON newline correction, shared fast checks and **15 focused
settings/inspector/search tests passed on both endpoints**. Seven new tests cover
settings/default persistence, protected clear/narrow focus/themes/tree wrapping,
active capture, exact capture admission and rejected updates, memory snapshots,
RAM eviction and independent higher-budget cache owners using real files.
Initial concurrent full checks exposed the existing14 test's interim view/selection
readiness assertion; it now waits for coherent selected membership under its same
five-second deadline and verifies original result records. Full rerun passed.

Purposeful SVG snapshots were rasterized and visually inspected; the checks caught
compact-button clipping and the syntax newline geometry bug, both corrected with
regressions. Evidence, logs and final handoff:
`/private/tmp/slogger-tui-implementation/ticket21-notes.md` and `preferences-visuals/`.
This is native headless/rendered evidence, not emulator/SSH/Linux/multiplexer,
clipboard-acceptance, total RSS/CPU or1–5GB qualification. Those remain23/24.
Documentation/API/tooling ownership and changelog were updated. Environments were
reused without reinstalling/repointing primary or creating user cache/config files.
