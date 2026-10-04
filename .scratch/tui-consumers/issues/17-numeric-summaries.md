# 17: Summarize numeric fields exactly

**What to build:** Selecting a numeric field returns count, sum, mean,
minimum, and maximum for the complete present-field scope.

**Blocked by:** 16

**Status:** ready-for-agent

Type: task

Source: [Native IXR investigation TUI specification](../spec.md). This is a production slice of the approved native design; resolved prototype work is evidence, not its implementation.

- [ ] Numeric null behavior, incompatible false/non-numeric/nonfinite values,
  empty scopes, exact large integers, and compensated floating reductions
  agree with the reference. Count includes present null rows as specified.
- [ ] Bounded/spill reduction avoids naive batch-sum or batch-mean shortcuts;
  cancellation, errors, and cleanup preserve the last successful pane.
- [ ] Nested numeric paths and literal keys work without injecting application
  fields. Metric selection is editable and errors give useful type guidance.
- [ ] Keep reusable operations headless and explicitly scoped, with structured records, separate origins/status/diagnostics, bounded working storage, and unchanged IXR primitive semantics. TUI workflow and presentation state stay in the consumer; CLI/MCP transports remain outside this ticket.
- [ ] Add behavior tests through Investigation session operations using real JSONL inputs and an installed package, plus focused native interaction tests where applicable. Cover this slice's errors, cleanup, and stale-result behavior where relevant; do not replace complete operations with previews.
- [ ] Update current documentation and the changelog for public behavior, and run the appropriate shared development checks. Preserve optional dependencies, logging/schema compatibility, and Python 3.10/3.13 endpoint contracts when typing or attribution changes.

## Coordination

The claimant owns this slice's behavior and tests. Before concurrent implementation, record owners for overlapping Investigation session, resource/job, execution, or native UI interfaces and name the implementer responsible for integration and test/import reconciliation. Coordinate shared-module edits without adding artificial blocking edges. Record the integration revision and verified editable environment when claiming the ticket.
