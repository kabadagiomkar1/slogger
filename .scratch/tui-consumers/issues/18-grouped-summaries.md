# 18: Group summaries by multiple and nested fields

**What to build:** The aggregate editor adds multiple grouping fields and
metrics, with exact paged summaries over nested or literal-key fields.

**Blocked by:** 17

**Status:** resolved

Type: task

Source: [Native IXR investigation TUI specification](../spec.md). This is a production slice of the approved native design; resolved prototype work is evidence, not its implementation.

- [x] Extend/reuse collision-safe shared path binding, preserve literal top-level
  grouping compatibility, and leave source application records untouched.
- [x] Secondary grouping keys preserve missing/null and typed numeric/bool rules;
  only the selected aggregate field receives the automatic presence guard.
- [x] High-cardinality groups preserve first appearance and complete reductions
  with bounded working memory, disk admission, progress, and cancellation.
- [x] Keep reusable operations headless and explicitly scoped, with structured records, separate origins/status/diagnostics, bounded working storage, and unchanged IXR primitive semantics. TUI workflow and presentation state stay in the consumer; CLI/MCP transports remain outside this ticket.
- [x] Add behavior tests through Investigation session operations using real JSONL inputs and an installed package, plus focused native interaction tests where applicable. Cover this slice's errors, cleanup, and stale-result behavior where relevant; do not replace complete operations with previews.
- [x] Update current documentation and the changelog for public behavior, and run the appropriate shared development checks. Preserve optional dependencies, logging/schema compatibility, and Python 3.10/3.13 endpoint contracts when typing or attribution changes.

## Coordination

Ticket18 owns collision-safe grouping bindings, complete indexed per-group numeric
replay/results and native grouping configuration. Reuse17's shared reference
validation/finalization and preserve source/configured-metric ordering, exact
integers, typed first representatives, missing versus null secondary keys and
16's selected-field presence guard. Public literal top-level QueryPlan grouping
contracts remain stable; nested bindings stay explicit and out of application data.

19 concurrently owns native aggregate follow/detach scope/editor state,21 owns
settings/resources/themes, and15 later owns filtered tree context. Coordinate
additive AggregateScope/request snapshots and consumer draft/result labels directly
with19; grouping and numeric metrics must work in every explicit input scope.
Preserve job/view leases, managed disk growth, cancellation/cleanup and shutdown
guards. F5/F6 field/results, F7/F8 search, F9 metrics, F10 settings and Ctrl+R
refresh remain reserved; grouping may use palette and normal focus navigation.
The merger reconciles shared aggregation/app contracts, imports, docs and combined
native behavior. Shared-file overlap adds no semantic blocker.

Claimed against clean integration `5209f56`, with17 resolved. Worktree
`codex/tui-18`: `/Users/omkar.kabadagi/.codex/worktrees/tui-18/slogger`, prepared
at `c8d1001`; merge latest integration before work. Verified own editable
interpreters: `/private/tmp/slogger-tui-18-env/bin/python` (3.13, registered) and
`/private/tmp/slogger-tui-18-py310/bin/python` (3.10), actual Polars/Textual present.
Reuse without reinstalling or repointing primary. Notes under
`/private/tmp/slogger-tui-implementation/`: context.md, ticket17-notes.md,
ticket16-notes.md, execution-notes.md and refresh-coordination-notes.md.19 is
`/root/implement_tui_19`; its latest branch/notes must be reconciled before done.


## Resolution

Implemented exact multiple/nested captured grouping with immutable tooling-only
`GroupBinding` paths and explicit derived output names, without source-record
injection or changes to literal-key QueryPlan grouping. Both categorical counts
and numeric summaries accept ordered grouping bindings in an explicit successful
input scope. Selected-field presence precedes grouping/admission; secondary
missing/null groups, bool/number identity, numeric ties and first typed/signed
representatives retain reference semantics. Complete groups remain disk-backed,
first-appearance ordered and arbitrarily paged with separate `None` origins.

Grouped numeric contributions use a separately admitted indexed ordinal spool;
whole-input validation precedes first-group/configured-metric replay with exact
integer totals, original-sequence compensated float reductions and reference error
precedence. Bounded point reads finalize result rows; staging statement caches are
disabled and SQLite page sizing matches managed growth accounting. Spool/index
files are removed before publication, and errors/cancellation/close preserve input
leases, cleanup diagnostics and prior results.

Native Group by accepts comma-separated exact paths and optional `as` aliases,
including quoted names and punctuation inside literal paths. F9 then Tab or the
palette focuses grouping without displacing reserved keys. Requested configuration,
newer drafts and successful scope labels stay distinct through Main changes and
supersession. Collision guidance explicitly suggests aliases for valid application
fields named count/sum/value. Current API/native/architecture/capability/domain docs
and changelog describe the delivered behavior.19 will adopt this slice and verify
combined detached/native grouping before its own resolution; shared-file overlap
was not treated as a semantic blocker.

Confirmed prepared ancestry and adopted integrationdd91a4d before work, then latest
settings/runtime-limit integration57469b5 in e063194. Final source8adfb87 includes
staging correction19f0163 and9headless realJSONL grouping tests plus3focused native
interaction tests. Full shared docs/Ruff/Pyrefly/pytest passed **479 tests on each
Python3.13/3.10 endpoint** with own verified editable environments and actual
Polars/Textual. Latest integration ancestry confirmed again before resolution.
Logs and interface/evidence notes are saved under
`/private/tmp/slogger-tui-implementation/ticket18-notes.md` and
`ticket18-check-py313.log` / `ticket18-check-py310.log` beside it.

A focused exact-source traced-allocation probe at19f0163 measured300/3000/30000
numeric groups using64KiB working admission and1KiB browse cache. Peak traced
109,505/175,232/172,704 bytes; retained afterGC7,743/7,029/6,978. Complete result disk
57,376/466,976/5,251,104 bytes reclaimed to baseline on close. This measures runtime
allocation and admitted working data separately; it excludes SQLite native/OS/RSS
and does not assert a total64KiB process bound or production-scale acceptance.
No actual emulator, clipboard, SSH/multiplexer, Linux or1–5GB latency/RSS/CPU
qualification was performed or claimed;23/24 retain that evidence work.
