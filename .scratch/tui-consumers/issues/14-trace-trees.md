# 14: Explore complete cross-file trace trees

**What to build:** The complete captured dataset can be explored as a paged,
foldable trace/span tree with honest lifecycle and relationship evidence.

**Blocked by:** 06

**Status:** ready-for-agent

Type: task

Source: [Native IXR investigation TUI specification](../spec.md). This is a production slice of the approved native design; resolved prototype work is evidence, not its implementation.

- [ ] Trace ID and trace-plus-span ID provide identity; names are labels. Roots,
  siblings, and records preserve file order and first appearance.
- [ ] Single/all fold controls, left/right navigation, mouse actions, and flat/tree
  switching preserve selected record identity where possible.
- [ ] Untraced records, missing parents, incomplete/conflicting spans, and cycles
  retain all source evidence without inventing duration or trustworthy parents.
- [ ] Reconstruction/indexing is background, disk-backed, resource-accounted, and
  complete beyond the former preview cap. Canonical lifecycle events are used.
- [ ] This slice demos the unfiltered tree; 15 adds the filtered/search cross-view
  behavior. Unsupported interim combinations are indicated rather than misleading.
- [ ] Keep reusable operations headless and explicitly scoped, with structured records, separate origins/status/diagnostics, bounded working storage, and unchanged IXR primitive semantics. TUI workflow and presentation state stay in the consumer; CLI/MCP transports remain outside this ticket.
- [ ] Add behavior tests through Investigation session operations using real JSONL inputs and an installed package, plus focused native interaction tests where applicable. Cover this slice's errors, cleanup, and stale-result behavior where relevant; do not replace complete operations with previews.
- [ ] Update current documentation and the changelog for public behavior, and run the appropriate shared development checks. Preserve optional dependencies, logging/schema compatibility, and Python 3.10/3.13 endpoint contracts when typing or attribution changes.

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
