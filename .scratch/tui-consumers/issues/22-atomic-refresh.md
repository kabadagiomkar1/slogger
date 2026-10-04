# 22: Refresh without losing the latest investigation state

**What to build:** Explicit refresh captures separately while the old
investigation stays usable, then publishes a coherent replacement atomically.

**Blocked by:** 07, 15, 18, 19, 21

**Status:** ready-for-agent

Type: task

Source: [Native IXR investigation TUI specification](../spec.md). This is a production slice of the approved native design; resolved prototype work is evidence, not its implementation.

- [ ] Reconcile main/independent filters, search/options, tree state, panes,
  preferences, and aggregate configuration edited during replacement capture.
  Reapply the latest active scopes before publication; no unfiltered flash.
- [ ] Restore selection/pins only for verified identical source occurrences;
  changed, disappeared, or ambiguous identities produce explicit diagnostics.
- [ ] Failed/canceled or over-budget refresh keeps the old complete dataset and
  result handles usable. Active plus replacement storage remains accounted.
- [ ] Controlled interleavings demonstrate stale old jobs cannot publish into the
  new dataset, and unsuccessful staging is safely cleaned.
- [ ] Keep reusable operations headless and explicitly scoped, with structured records, separate origins/status/diagnostics, bounded working storage, and unchanged IXR primitive semantics. TUI workflow and presentation state stay in the consumer; CLI/MCP transports remain outside this ticket.
- [ ] Add behavior tests through Investigation session operations using real JSONL inputs and an installed package, plus focused native interaction tests where applicable. Cover this slice's errors, cleanup, and stale-result behavior where relevant; do not replace complete operations with previews.
- [ ] Update current documentation and the changelog for public behavior, and run the appropriate shared development checks. Preserve optional dependencies, logging/schema compatibility, and Python 3.10/3.13 endpoint contracts when typing or attribution changes.

## Coordination

The claimant owns this slice's behavior and tests. Before concurrent implementation, record owners for overlapping Investigation session, resource/job, execution, or native UI interfaces and name the implementer responsible for integration and test/import reconciliation. Coordinate shared-module edits without adding artificial blocking edges. Record the integration revision and verified editable environment when claiming the ticket.
