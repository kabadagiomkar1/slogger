# 21: Save useful global preferences and themes

**What to build:** A keyboard-accessible settings view changes real presentation
and resource behavior, with coherent dark/light themes and explicit saved defaults.

**Blocked by:** 08, 09, 20

**Status:** claimed

Type: task

Source: [Native IXR investigation TUI specification](../spec.md). This is a production slice of the approved native design; resolved prototype work is evidence, not its implementation.

- [ ] Theme, wrap, timestamp, duration, inspector line numbers, pane size/visibility,
  resource limits, expiry, usage, and protected clearing are usable options.
- [ ] Session adjustments do not implicitly overwrite global defaults; saving is
  explicit. Query/search/navigation histories remain session-only.
- [ ] Narrow layouts preserve access and both themes provide readable control,
  JSON, selection, error, and search-highlight states.
- [ ] Keep reusable operations headless and explicitly scoped, with structured records, separate origins/status/diagnostics, bounded working storage, and unchanged IXR primitive semantics. TUI workflow and presentation state stay in the consumer; CLI/MCP transports remain outside this ticket.
- [ ] Add behavior tests through Investigation session operations using real JSONL inputs and an installed package, plus focused native interaction tests where applicable. Cover this slice's errors, cleanup, and stale-result behavior where relevant; do not replace complete operations with previews.
- [ ] Update current documentation and the changelog for public behavior, and run the appropriate shared development checks. Preserve optional dependencies, logging/schema compatibility, and Python 3.10/3.13 endpoint contracts when typing or attribution changes.

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
