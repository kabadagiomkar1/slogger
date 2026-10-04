# 20: Reopen verified datasets and reclaim cache safely

**What to build:** Reopening verifies source contents before reusing completed
capture/index data, and resource controls reclaim only safe unused storage.

**Blocked by:** 06

**Status:** ready-for-agent

Type: task

Source: [Native IXR investigation TUI specification](../spec.md). This is a production slice of the approved native design; resolved prototype work is evidence, not its implementation.

- [ ] Verify current boundaries, ordered/repeated inputs, content changes even
  with unchanged size/mtime, versions, and corruption. A saved prefix followed
  by appends cannot count as the current complete dataset.
- [ ] Choose durable cache location/versioning and protect active datasets across
  processes. Recover stale ownership and clean expired/abandoned captures.
- [ ] Account for allocated capture/index/result/staging/journal/spill storage;
  expose usage, configurable budget/expiry, and protected clear controls.
- [ ] Default to provisional 10 GB managed disk and seven-day inactivity expiry;
  resource failures stay actionable. RAM browsing limits are configurable and
  distinct from total process memory. 24 selects a measured default.
- [ ] Verification/reuse progress is visible; cache reuse does not imply zero I/O.
- [ ] Keep reusable operations headless and explicitly scoped, with structured records, separate origins/status/diagnostics, bounded working storage, and unchanged IXR primitive semantics. TUI workflow and presentation state stay in the consumer; CLI/MCP transports remain outside this ticket.
- [ ] Add behavior tests through Investigation session operations using real JSONL inputs and an installed package, plus focused native interaction tests where applicable. Cover this slice's errors, cleanup, and stale-result behavior where relevant; do not replace complete operations with previews.
- [ ] Update current documentation and the changelog for public behavior, and run the appropriate shared development checks. Preserve optional dependencies, logging/schema compatibility, and Python 3.10/3.13 endpoint contracts when typing or attribution changes.

## Coordination

The claimant owns this slice's behavior and tests. Before concurrent implementation, record owners for overlapping Investigation session, resource/job, execution, or native UI interfaces and name the implementer responsible for integration and test/import reconciliation. Coordinate shared-module edits without adding artificial blocking edges. Record the integration revision and verified editable environment when claiming the ticket.
