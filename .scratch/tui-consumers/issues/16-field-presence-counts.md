# 16: Count values where the selected field exists

**What to build:** Selecting a console/JSON field or a keyboard field target
opens exact categorical counts in a lower pane following the Main filter.

**Blocked by:** 09, 10

**Status:** resolved

Type: task

Source: [Native IXR investigation TUI specification](../spec.md). This is a production slice of the approved native design; resolved prototype work is evidence, not its implementation.

- [x] The visible span label selects its canonical span field; console and JSON
  targets resolve the same field paths regardless of display spelling.
- [x] Compose selected-field presence into the explicit operation scope before
  count/grouping or resource admission. Missing is excluded; null/zero/false
  remain present. The public row-count primitive retains its existing meaning.
- [x] Typed scalar grouping, first-appearance order, repeated record occurrences,
  empty results, and collection/type errors preserve IXR semantics.
- [x] Selected nested paths and literal keys use collision-safe out-of-band binding
  for value counts. This slice introduces that single-path capability; 18
  extends/reuses it for multiple grouping fields.
- [x] Count the complete scope and page high-cardinality groups without preview
  caps, synthetic fields, or fabricated aggregate origins.
- [x] Main-filter changes produce correctly scoped background jobs; pending/failed
  results retain their old scope label and stale jobs cannot publish.
- [x] Bounded count/group storage participates in the shared resource contract.
- [x] Keep reusable operations headless and explicitly scoped, with structured records, separate origins/status/diagnostics, bounded working storage, and unchanged IXR primitive semantics. TUI workflow and presentation state stay in the consumer; CLI/MCP transports remain outside this ticket.
- [x] Add behavior tests through Investigation session operations using real JSONL inputs and an installed package, plus focused native interaction tests where applicable. Cover this slice's errors, cleanup, and stale-result behavior where relevant; do not replace complete operations with previews.
- [x] Update current documentation and the changelog for public behavior, and run the appropriate shared development checks. Preserve optional dependencies, logging/schema compatibility, and Python 3.10/3.13 endpoint contracts when typing or attribution changes.

## Coordination

Ticket16 owns shared out-of-band path binding and bounded typed categorical
aggregation/result paging, plus native field targeting and the lower aggregate
pane. Reuse09 exact JSON paths/FieldRequested and08 canonical console span
selection; preserve10 input leases, scoped operation lifecycle and original
identities.13 owns search/matching/highlights;11 owns reusable FilterEditor
completion;14 owns trace trees.20 owns global managed-disk cache/admission and
external-growth contracts. Keep native defaults/follow-main state out of shared
operations;17/18 will reuse these bindings/reducers and19 owns detachment.

Use separate aggregate modules and additive app/console hooks. The merger owns
shared import/composition/CSS/documentation reconciliation and combined native
regressions. Shared files do not add semantic blockers.

Claimed against integration `37d2f3a`, with09/10 resolved. Worktree `codex/tui-16`:
`/Users/omkar.kabadagi/.codex/worktrees/tui-16/slogger`; prepared at `ee7cfc8`,
merge latest integration before work. Verified editable interpreters:
`/private/tmp/slogger-tui-16-env/bin/python` (3.13, registered) and
`/private/tmp/slogger-tui-16-py310/bin/python` (3.10), with actual Polars/Textual.
Reuse these environments; do not reinstall or repoint primary. Execution pointers:
`/private/tmp/slogger-tui-implementation/context.md`, `execution-notes.md`,
`filter-search-aggregate-coordination.md` and `ticket09/10/14-notes.md`.


## Resolution

Delivered complete `Investigation.count_values` over explicit dataset/view scopes,
mandatory selected-field presence and reusable out-of-band exact `FieldBinding`.
Typed scalar identities, huge integers, numeric ties and first representatives
remain reference-compatible; missing is excluded and null/zero/false remain present.
Public row count and literal-key QueryPlan grouping retain their existing meaning.
Complete derived groups are admitted on disk and paged with `None` origins, without
record injection or preview caps. View leases, cancellation, shared global admission,
structured errors and cleanup preserve the captured dataset and earlier results.

Native console/JSON targets and the F5 field editor open a compact lower pane.
Alt+arrows/Enter, Ctrl/double click, F6 result navigation and forward/backward pane
cycling cover keyboard/mouse entry. Counts follow successful Main views; stale
requests cannot publish, retained output keeps its old label, and automatic Main
changes preserve independent field drafts and hidden-pane visibility. Native
polling stops after shutdown, including the existing capture/filter/tree callbacks.

Own verified editable environments were reused. Integration6f3c5d9 (including11/20)
was merged before finalization; full shared checks against source revision81f06c5
passed docs/Ruff/Pyrefly and **429 tests on each Python3.13/3.10 endpoint**, with actual
Polars/Textual. Eight headless and four focused native tests exercise this slice
through the approved real-file/session and native interaction seams, including
12,057 exact groups under tiny cache/page limits, path/type/presence distinctions,
repeated inputs, scoped leases, disk/cancel/OS cleanup errors, and retained/stale
Main/count state. The existing tree/filter native wait uses a monotonic deadline
for concurrent endpoint load while retaining its behavior assertions.

Current API, native guide, architecture/capability documentation and changelog
updated. Evidence/API handoff: `/private/tmp/slogger-tui-implementation/ticket16-notes.md`
and `ticket16-check-py313.log` / `ticket16-check-py310.log` beside it. No actual terminal,
SSH, clipboard, Linux or1–5GB/RSS qualification is claimed. Numeric summaries,
multiple grouping paths and detached filters remain tickets17/18/19.
