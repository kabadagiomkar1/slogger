# 15: Filter and search through ancestor context

**What to build:** Tree mode honors the applied filter while retaining marked
ancestors, and search reveals matching records through folded paths.

**Blocked by:** 13, 14

**Status:** resolved

Type: task

Source: [Native IXR investigation TUI specification](../spec.md). This is a production slice of the approved native design; resolved prototype work is evidence, not its implementation.

- [x] Ancestor context explains matches but is not itself a filter/search match or
  aggregate contributor merely because it is displayed.
- [x] Search next/previous reveals required ancestors and keeps source-order
  navigation and flat/tree selection coherent.
- [x] Filter/search generation changes cannot publish stale tree membership or
  context; uncertainty remains honestly represented.
- [x] Keep reusable operations headless and explicitly scoped, with structured records, separate origins/status/diagnostics, bounded working storage, and unchanged IXR primitive semantics. TUI workflow and presentation state stay in the consumer; CLI/MCP transports remain outside this ticket.
- [x] Add behavior tests through Investigation session operations using real JSONL inputs and an installed package, plus focused native interaction tests where applicable. Cover this slice's errors, cleanup, and stale-result behavior where relevant; do not replace complete operations with previews.
- [x] Update current documentation and the changelog for public behavior, and run the appropriate shared development checks. Preserve optional dependencies, logging/schema compatibility, and Python 3.10/3.13 endpoint contracts when typing or attribution changes.

## Coordination

Ticket15 owns explicit filtered-tree membership and marked ancestor context,
search reveal through folded paths, and coherent flat/tree selection. Preserve
14's complete immutable trace evidence, first-appearance ordering and uncertainty;
displayed context is not a query/search match or aggregate contributor.13 owns
semantic search membership/projection and native highlight/navigation controls.
Use scoped result handles, leases and consumer generations to reject stale work.

21 concurrently owns bounded tree wrapped-row handling and palette themes;
coordinate tree viewport additions directly and preserve its wrap behavior.
17/18 own aggregate reductions/grouping,19 owns detached scope/editor state.
Keep Main result membership authoritative and avoid coupling aggregate input to
display context.22 later owns atomic replacement. The merger reconciles tree,
app/controller interfaces, imports, docs and combined search/filter/tree tests.
File overlap does not add semantic blockers. Existing key bindings remain intact.

Claimed against clean integration `eaab141`, with13/14 resolved. Worktree
`codex/tui-15`: `/Users/omkar.kabadagi/.codex/worktrees/tui-15/slogger`, prepared
at `c8d1001`; merge latest integration before work. Verified own editable
interpreters: `/private/tmp/slogger-tui-15-env/bin/python` (3.13, registered) and
`/private/tmp/slogger-tui-15-py310/bin/python` (3.10), actual Polars/Textual present.
Reuse without reinstalling or repointing primary. Notes under
`/private/tmp/slogger-tui-implementation/`: context.md, ticket13-notes.md,
ticket14-notes.md, ticket20-notes.md and refresh-coordination-notes.md. Dispatch
when a concurrency slot is available; latest21 notes describe viewport wrapping.


## Resolution

Implemented explicit `Investigation.build_tree(input_view=None,
request_generation=0, background=True)` delivery over same-session leased
membership. Complete capture remains the relationship/lifecycle evidence source;
an indexed disk pass retains only admitted record leaves and their complete
ancestor closure. `TreeScope` carries population/input scope/generation.
`TraceTree.record_count` is admitted membership, `evidence_record_count` is complete
capture, and structural `TreeRow.match_count`/`context_only` distinguish admitted
direct contributors from ancestors. `TreeRow.record_count` and `record_page(node)`
retain **all original direct evidence**, including excluded records; evidence
inspection never becomes filter/search/aggregate membership. Original ordering,
origins, repeated occurrences and conservative uncertainty remain intact.

Native B supports applied Main and active search, retaining prior successful tree
through pending Main changes and rebuilding after successful publication. A
single active worker/latest request rejects stale actual owners, scopes and
generations; queued tree selection checks its actual handle as well. Search
navigates source-order matches and reveals folded ancestors with one target and
bounded indexed path lookup, without a depth-sized fold set. Context labels are
explicit and have no semantic record search highlighting. Flat positions remain
separate from captured ordinals; wrap, sparse folds, themes, pins and shortcuts
survive. Main `RecordView` continues to feed search/aggregate jobs independently
of context; grouped and detached-scope composition is preserved.

Approved real JSONL Investigation/native seams were used, with filesystem
scheduling/unlink injection only at OS boundaries. Eight added behavior cases
cover explicit evidence-versus-membership populations, 20,010 admitted repeated
occurrences, 1,300-level ancestor closure, empty/foreign/closed inputs, membership
leases, cancellation/failed cleanup with usable capture, old Main scope finishing
late, native filtered search/highlights/next/previous/pins/flat position, and a
600-level folded native path beyond sparse fold capacity. Existing uncertainty,
wrap, search and aggregate tests remain green. Current API, native guide,
ownership/capability docs and changelog updated.

Initial prepared `c8d1001` fast-forwarded to `57469b5`; implementation `7062ae8`
and compatibility follow-up `49586d1` adopted grouped `72989ea` via `530ea43`, then
committed detached/IPC source `e580e6c` via `9057ee8`. Final integration `01de63f`
is an ancestor; its tracker-only merge has an identical source/test tree to
`9057ee8`. The full shared docs/Ruff/Pyrefly/pytest command passed **496 tests on
each endpoint** with own unchanged verified editable interpreters:
`/private/tmp/slogger-tui-15-env/bin/python` (3.13.9) and
`/private/tmp/slogger-tui-15-py310/bin/python` (3.10.20), actual Polars/Textual.
Pytest wall times 159.85/169.65 seconds are suite evidence, not feature benchmarks.
Focused 35 tree/search/preferences checks passed each endpoint; 20 combined
native tree/search/grouped-summary checks passed after grouping integration.
Logs and detailed refresh/controller handoff:
`/private/tmp/slogger-tui-implementation/ticket15-notes.md`,
`ticket15-check-py313.log`, `ticket15-check-py310.log`.

No primary edits, installs/repointing, import-time files/handlers, logging/schema
or IXR primitive changes. No actual terminal/SSH/multiplexer/Linux/clipboard or
1–5 GB/RSS/CPU qualification claimed; user-run terminal evidence and scale work
remain tickets23/24.
