# 07: Browse progressive capture and recover from opening failures

**What to build:** A large investigation becomes browseable during capture,
with honest progress, safe cancellation, and retained partial records on failure.

**Blocked by:** 06

**Status:** ready-for-agent

Type: task

Source: [Native IXR investigation TUI specification](../spec.md). This is a production slice of the approved native design; resolved prototype work is evidence, not its implementation.

- [ ] Background capture permits console selection and JSON inspection of the
  captured prefix; the shared readiness contract keeps all dataset-wide
  operations unavailable until complete, including operations added by other slices.
- [ ] Failed/canceled opening retains already captured records until session close,
  marked incomplete, with actionable diagnostics and no reusable-complete flag.
- [ ] Observed source truncation/replacement/mutation, file access failures, disk
  exhaustion, and declared oversized-record limits cannot silently omit data.
- [ ] Closing/canceling releases owned resources and superseded capture work cannot
  publish into a newer investigation.
- [ ] Keep reusable operations headless and explicitly scoped, with structured records, separate origins/status/diagnostics, bounded working storage, and unchanged IXR primitive semantics. TUI workflow and presentation state stay in the consumer; CLI/MCP transports remain outside this ticket.
- [ ] Add behavior tests through Investigation session operations using real JSONL inputs and an installed package, plus focused native interaction tests where applicable. Cover this slice's errors, cleanup, and stale-result behavior where relevant; do not replace complete operations with previews.
- [ ] Update current documentation and the changelog for public behavior, and run the appropriate shared development checks. Preserve optional dependencies, logging/schema compatibility, and Python 3.10/3.13 endpoint contracts when typing or attribution changes.

## Coordination

The claimant owns this slice's behavior and tests. Before concurrent implementation, record owners for overlapping Investigation session, resource/job, execution, or native UI interfaces and name the implementer responsible for integration and test/import reconciliation. Coordinate shared-module edits without adding artificial blocking edges. Record the integration revision and verified editable environment when claiming the ticket.
