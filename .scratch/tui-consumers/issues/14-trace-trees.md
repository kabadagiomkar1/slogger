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

The claimant owns this slice's behavior and tests. Before concurrent implementation, record owners for overlapping Investigation session, resource/job, execution, or native UI interfaces and name the implementer responsible for integration and test/import reconciliation. Coordinate shared-module edits without adding artificial blocking edges. Record the integration revision and verified editable environment when claiming the ticket.
