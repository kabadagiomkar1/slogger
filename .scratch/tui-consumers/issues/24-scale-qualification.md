# 24: Qualify 1–5 GB investigations and choose resource defaults

**What to build:** Reproducible measurements establish the production resource
envelope and RAM default for complete 1 GB and 5 GB investigations.

**Blocked by:** 22

**Status:** ready-for-agent

Type: task

Source: [Native IXR investigation TUI specification](../spec.md). This is a production slice of the approved native design; resolved prototype work is evidence, not its implementation.

- [ ] Representative 100–200 MB files include custom/sparse/nested fields, long
  messages, cross-file traces, and high-cardinality groups. Record revision,
  input identity, machine, and cold/warm OS-cache conditions.
- [ ] Measure first browseable/complete opening, verified reuse cost, filters,
  search, completion, trees, aggregates, idle/active CPU, peak RSS, and total/
  peak disk including refresh staging. Account for failures under 10 GB honestly.
- [ ] Verify bounded working memory beyond browsing-cache admission; select and
  document a practical RAM default and admitted-record/resource envelope.
- [ ] Existing prototype timings are historical. No invented latency/CPU guarantees
  or sampled results replace required correctness. Correctness regressions are
  addressed in their owning slices rather than hidden behind qualification.
- [ ] Terminal validation and scale qualification can run concurrently; neither
  is a semantic prerequisite for the other's independent evidence.
- [ ] Keep reusable operations headless and explicitly scoped, with structured records, separate origins/status/diagnostics, bounded working storage, and unchanged IXR primitive semantics. TUI workflow and presentation state stay in the consumer; CLI/MCP transports remain outside this ticket.
- [ ] Add behavior tests through Investigation session operations using real JSONL inputs and an installed package, plus focused native interaction tests where applicable. Cover this slice's errors, cleanup, and stale-result behavior where relevant; do not replace complete operations with previews.
- [ ] Update current documentation and the changelog for public behavior, and run the appropriate shared development checks. Preserve optional dependencies, logging/schema compatibility, and Python 3.10/3.13 endpoint contracts when typing or attribution changes.

## Coordination

The claimant owns this slice's behavior and tests. Before concurrent implementation, record owners for overlapping Investigation session, resource/job, execution, or native UI interfaces and name the implementer responsible for integration and test/import reconciliation. Coordinate shared-module edits without adding artificial blocking edges. Record the integration revision and verified editable environment when claiming the ticket.
