# 16: Count values where the selected field exists

**What to build:** Selecting a console/JSON field or a keyboard field target
opens exact categorical counts in a lower pane following the Main filter.

**Blocked by:** 09, 10

**Status:** ready-for-agent

Type: task

Source: [Native IXR investigation TUI specification](../spec.md). This is a production slice of the approved native design; resolved prototype work is evidence, not its implementation.

- [ ] The visible span label selects its canonical span field; console and JSON
  targets resolve the same field paths regardless of display spelling.
- [ ] Compose selected-field presence into the explicit operation scope before
  count/grouping or resource admission. Missing is excluded; null/zero/false
  remain present. The public row-count primitive retains its existing meaning.
- [ ] Typed scalar grouping, first-appearance order, repeated record occurrences,
  empty results, and collection/type errors preserve IXR semantics.
- [ ] Selected nested paths and literal keys use collision-safe out-of-band binding
  for value counts. This slice introduces that single-path capability; 18
  extends/reuses it for multiple grouping fields.
- [ ] Count the complete scope and page high-cardinality groups without preview
  caps, synthetic fields, or fabricated aggregate origins.
- [ ] Main-filter changes produce correctly scoped background jobs; pending/failed
  results retain their old scope label and stale jobs cannot publish.
- [ ] Bounded count/group storage participates in the shared resource contract.
- [ ] Keep reusable operations headless and explicitly scoped, with structured records, separate origins/status/diagnostics, bounded working storage, and unchanged IXR primitive semantics. TUI workflow and presentation state stay in the consumer; CLI/MCP transports remain outside this ticket.
- [ ] Add behavior tests through Investigation session operations using real JSONL inputs and an installed package, plus focused native interaction tests where applicable. Cover this slice's errors, cleanup, and stale-result behavior where relevant; do not replace complete operations with previews.
- [ ] Update current documentation and the changelog for public behavior, and run the appropriate shared development checks. Preserve optional dependencies, logging/schema compatibility, and Python 3.10/3.13 endpoint contracts when typing or attribution changes.

## Coordination

The claimant owns this slice's behavior and tests. Before concurrent implementation, record owners for overlapping Investigation session, resource/job, execution, or native UI interfaces and name the implementer responsible for integration and test/import reconciliation. Coordinate shared-module edits without adding artificial blocking edges. Record the integration revision and verified editable environment when claiming the ticket.
