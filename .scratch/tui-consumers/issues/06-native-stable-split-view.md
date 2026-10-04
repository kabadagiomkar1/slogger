# 06: Open supplied logs in a stable native split view

**What to build:** An optional installed terminal application opens supplied
files into a stable disk-captured dataset, pages the console stream in input
order, and shows the selected record's complete JSON in a narrower right pane.

**Blocked by:** none

**Status:** ready-for-agent

Type: task

Source: [Native IXR investigation TUI specification](../spec.md). This is a production slice of the approved native design; resolved prototype work is evidence, not its implementation.

- [ ] Ordered and repeated input occurrences, opening byte boundaries, and source
  physical lines survive capture and paging. Later appends do not alter the
  captured investigation. No synthetic application metadata is injected.
  A shared completeness/readiness contract guards dataset-wide operations.
- [ ] Shared decoding handles malformed/non-object lines and valid final objects
  without newlines; diagnostics and original source locations remain accurate.
- [ ] Console defaults recognize real slogger timestamp/level/logger/message/span,
  hide known metadata, show user fields, and align message starts. Generic objects
  and real Unicode remain readable; demonstration messages use ASCII.
- [ ] Keyboard paging/selection and basic mouse selection synchronize the JSON
  inspector. Complete admitted records are available, with syntax colors and
  parsed-record indication rather than a fixed text preview cap.
- [ ] Capture, paging, record admission, and disk/RAM working storage have explicit
  resource contracts and clean close behavior. The basic resource-accounting
  mechanism exists from the first storage-producing operation; later slices
  account for their own indexes/results through it.
- [ ] Headless open/page/close operations work without Textual. Base logging/IXR
  imports create no files/handlers and optional dependency failures are useful.
- [ ] Initial opening is demoable after capture completes; 07 adds progressive
  browsing and its full interaction/failure policy.
- [ ] Keep reusable operations headless and explicitly scoped, with structured records, separate origins/status/diagnostics, bounded working storage, and unchanged IXR primitive semantics. TUI workflow and presentation state stay in the consumer; CLI/MCP transports remain outside this ticket.
- [ ] Add behavior tests through Investigation session operations using real JSONL inputs and an installed package, plus focused native interaction tests where applicable. Cover this slice's errors, cleanup, and stale-result behavior where relevant; do not replace complete operations with previews.
- [ ] Update current documentation and the changelog for public behavior, and run the appropriate shared development checks. Preserve optional dependencies, logging/schema compatibility, and Python 3.10/3.13 endpoint contracts when typing or attribution changes.

## Coordination

The claimant owns this slice's behavior and tests. Before concurrent implementation, record owners for overlapping Investigation session, resource/job, execution, or native UI interfaces and name the implementer responsible for integration and test/import reconciliation. Coordinate shared-module edits without adding artificial blocking edges. Record the integration revision and verified editable environment when claiming the ticket.
