# 14: Explore complete cross-file trace trees

**What to build:** The complete captured dataset can be explored as a paged,
foldable trace/span tree with honest lifecycle and relationship evidence.

**Blocked by:** 06

**Status:** resolved

Type: task

Source: [Native IXR investigation TUI specification](../spec.md). This is a production slice of the approved native design; resolved prototype work is evidence, not its implementation.

- [x] Trace ID and trace-plus-span ID provide identity; names are labels. Roots,
  siblings, and records preserve file order and first appearance.
- [x] Single/all fold controls, left/right navigation, mouse actions, and flat/tree
  switching preserve selected record identity where possible.
- [x] Untraced records, missing parents, incomplete/conflicting spans, and cycles
  retain all source evidence without inventing duration or trustworthy parents.
- [x] Reconstruction/indexing is background, disk-backed, resource-accounted, and
  complete beyond the former preview cap. Canonical lifecycle events are used.
- [x] This slice demos the unfiltered tree; 15 adds the filtered/search cross-view
  behavior. Unsupported interim combinations are indicated rather than misleading.
- [x] Keep reusable operations headless and explicitly scoped, with structured records, separate origins/status/diagnostics, bounded working storage, and unchanged IXR primitive semantics. TUI workflow and presentation state stay in the consumer; CLI/MCP transports remain outside this ticket.
- [x] Add behavior tests through Investigation session operations using real JSONL inputs and an installed package, plus focused native interaction tests where applicable. Cover this slice's errors, cleanup, and stale-result behavior where relevant; do not replace complete operations with previews.
- [x] Update current documentation and the changelog for public behavior, and run the appropriate shared development checks. Preserve optional dependencies, logging/schema compatibility, and Python 3.10/3.13 endpoint contracts when typing or attribution changes.

## Coordination

Owns disk-backed trace reconstruction/paging and the native tree viewport/folds.
Ticket07 owns capture/readiness and bounded writers;10 owns shared query/job/view
scopes, so coordinate operation lifecycle without replacing predicate semantics.
Ticket08 owns flat console layout/navigation,09 inspector state. Preserve ordinal
record identity and original evidence; names label nodes, never identify them.
Tree filtering/search integration belongs to15, but preserve explicit scopes so
interim unsupported combinations are honest. Read cache-trace-notes.md.

App compose, bindings, selection and imports overlap; each behavior owns its own
module/handler and merger agents reconcile all completed slices. Shared docs and
native tests retain all assertions. File overlap does not add blocking edges.

Prepared integration baseline: `06f8d03` on `codex/ixr-native-tui`.
Prepared isolated worktree: `/Users/omkar.kabadagi/.codex/worktrees/tui-14/slogger`.
Verified editable Python3.13: `/private/tmp/slogger-tui-14-env/bin/python`.
Verified editable Python3.10: `/private/tmp/slogger-tui-14-py310/bin/python`.
Both endpoint preflights passed. Claim and merge the latest integration branch
before implementation starts; merge it again before reporting completion.

Research pointers are under `/private/tmp/slogger-tui-implementation/`.

Claimed from integration `eabfa9a`; merge the current tip before starting.
Progressive capture07 is completed and queued for integration; use its final
writer/close/readiness notes before final reconciliation.


## Resolution

Implemented complete unfiltered trace evidence in `investigation/tree.py` with
explicit dataset/request scopes, background cancellation, bounded SQLite staging,
resource growth admission and paged structural/contributor navigation. Identity is
trace plus span ID; canonical names are labels. All source occurrences remain
leaves, including invalid/untraced records. Missing parents are placeholders;
contradictory/null/empty/invalid parents and cycle members have honest states.
Lifecycle uses only canonical starts/ends, retains multiplicity and summarizes
only unique valid observed status/duration. No inferred trace duration is added.

Native B switches flat/tree with stable captured ordinal selection and inspector
pins. Tree Space/Enter/click folds, Shift+Space toggles all, arrows navigate
relationships, pages/Home/End move visible rows, and Shift+Left/Right pans. Native
results publish only for the current requested dataset; cancellation keeps the
console usable. Applying Main leaves tree before its result publishes, and
pending/applied filter combinations remain explicitly unsupported until15.

Confirmed prepared06f8d03 ancestry, merged initial integration61b9a30 and inspector
ee7cfc8, then reconciled the completed10 integration (f8b26db plus claim docs).
Shared operation/view lifecycle and remove_file match10; external_growth matches
the agreed20 API and consumes reservations before reconciling actual allocation.
Complete-operation admission also rejects a session already closing before any
new worker construction. Source docs/API/architecture/capabilities/changelog updated.

Both installed editable endpoints passed final shared docs/Ruff/Pyrefly/pytest:
391tests on Python3.13.9 and3.10.20, with actual Polars1.44.2 and Textual8.2.8.
Focused behavior evidence includes20,010repeated record occurrences, a1300-level
span chain, cross-file/source order, canonical/conflicting lifecycle, invalid typed
IDs, parent/cycle evidence, staging resource failure, canceled scoped requests,
close cleanup, native folds/pins/narrow gating and Main position/ordinal separation.
Tests drive real JSONL through Investigation and focused native interactions;
SQLite-connect barriers are external scheduling boundaries for stale work.

Notes and final check logs: `/private/tmp/slogger-tui-implementation/ticket14-notes.md`,
`ticket14-check-py313.log`, `ticket14-check-py310.log`. Headless fixtures establish
complete behavior and structural admission, not1–5GB RSS/performance, real terminal,
SSH/multiplexer, clipboard or Linux qualification.15owns filtered ancestor/search
behavior;20owns durable cache/global allocation beyond the shared hook adopted here.
