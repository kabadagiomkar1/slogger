# 13: Search filtered records with live highlighting

**What to build:** Literal text search highlights as the user types and
navigates matching records inside the applied Main filter without filtering them.

**Blocked by:** 10

**Status:** ready-for-agent

Type: task

Source: [Native IXR investigation TUI specification](../spec.md). This is a production slice of the approved native design; resolved prototype work is evidence, not its implementation.

- [ ] Console/full-record scopes use complete decoded names/values, including
  hidden metadata in full scope; serialization escapes do not become matches.
- [ ] Case and Unicode whole-word options, immediate highlights, no typing-driven
  cursor movement, complete background record counts, and next/previous/wrap
  navigation are usable with clear option states.
- [ ] Changing scope, case, word options, or console-field visibility recomputes
  visible highlights and the complete match set, superseding prior work.
- [ ] Empty search clears matches. Filter/request changes invalidate stale match
  scopes; cancellation and pending status preserve the prior successful view.
- [ ] The complete match index is paged/disk-backed and resource-accounted.
- [ ] Keep reusable operations headless and explicitly scoped, with structured records, separate origins/status/diagnostics, bounded working storage, and unchanged IXR primitive semantics. TUI workflow and presentation state stay in the consumer; CLI/MCP transports remain outside this ticket.
- [ ] Add behavior tests through Investigation session operations using real JSONL inputs and an installed package, plus focused native interaction tests where applicable. Cover this slice's errors, cleanup, and stale-result behavior where relevant; do not replace complete operations with previews.
- [ ] Update current documentation and the changelog for public behavior, and run the appropriate shared development checks. Preserve optional dependencies, logging/schema compatibility, and Python 3.10/3.13 endpoint contracts when typing or attribution changes.

## Coordination

The claimant owns this slice's behavior and tests. Before concurrent implementation, record owners for overlapping Investigation session, resource/job, execution, or native UI interfaces and name the implementer responsible for integration and test/import reconciliation. Coordinate shared-module edits without adding artificial blocking edges. Record the integration revision and verified editable environment when claiming the ticket.
