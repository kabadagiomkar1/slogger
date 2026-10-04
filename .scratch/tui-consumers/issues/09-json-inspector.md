# 09: Inspect and compare complete JSON records

**What to build:** The right pane is independently navigable, resizeable,
toggleable, and pinnable, with complete record inspection and usable key targets.

**Blocked by:** 06

**Status:** ready-for-agent

Type: task

Source: [Native IXR investigation TUI specification](../spec.md). This is a production slice of the approved native design; resolved prototype work is evidence, not its implementation.

- [ ] Navigate long prettified JSON vertically/horizontally without a character
  preview cap; expose optional line numbers and retain valid-record indication.
- [ ] Hide/resize and pin/unpin have keyboard equivalents; selection and pinned
  inspection are distinct and source identity is visible.
- [ ] JSON key navigation exposes unambiguous nested/literal field targets for later
  field actions. Copy uses supported terminal capabilities or reports that it
  is unavailable; copied content is complete.
- [ ] Narrow resize and focus changes do not strand controls or discard a pin.
- [ ] Keep reusable operations headless and explicitly scoped, with structured records, separate origins/status/diagnostics, bounded working storage, and unchanged IXR primitive semantics. TUI workflow and presentation state stay in the consumer; CLI/MCP transports remain outside this ticket.
- [ ] Add behavior tests through Investigation session operations using real JSONL inputs and an installed package, plus focused native interaction tests where applicable. Cover this slice's errors, cleanup, and stale-result behavior where relevant; do not replace complete operations with previews.
- [ ] Update current documentation and the changelog for public behavior, and run the appropriate shared development checks. Preserve optional dependencies, logging/schema compatibility, and Python 3.10/3.13 endpoint contracts when typing or attribution changes.

## Coordination

The claimant owns this slice's behavior and tests. Before concurrent implementation, record owners for overlapping Investigation session, resource/job, execution, or native UI interfaces and name the implementer responsible for integration and test/import reconciliation. Coordinate shared-module edits without adding artificial blocking edges. Record the integration revision and verified editable environment when claiming the ticket.
