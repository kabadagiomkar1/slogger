# 19: Detach and reattach aggregate filters with completion

**What to build:** An aggregate can copy the currently applied Main filter
into an independent editor, refine it with full completion, and explicitly reattach.

**Blocked by:** 12, 16

**Status:** ready-for-agent

Type: task

Source: [Native IXR investigation TUI specification](../spec.md). This is a production slice of the approved native design; resolved prototype work is evidence, not its implementation.

- [ ] Both editors share syntax, key/value discovery, typed insertion, keyboard,
  and mouse interaction. Detachment copies applied rather than draft text.
- [ ] Detached scopes survive subsequent main changes without changing the main
  view; reattachment resumes following the latest applied Main filter.
- [ ] Scope generations, selected-field presence, retained-result labels, errors,
  and cancellation work consistently for all available aggregate metrics.
- [ ] Numeric/grouped metrics and detachment can evolve concurrently through the
  same explicit operation scope; dependencies do not impose a false sequence.
- [ ] Keep reusable operations headless and explicitly scoped, with structured records, separate origins/status/diagnostics, bounded working storage, and unchanged IXR primitive semantics. TUI workflow and presentation state stay in the consumer; CLI/MCP transports remain outside this ticket.
- [ ] Add behavior tests through Investigation session operations using real JSONL inputs and an installed package, plus focused native interaction tests where applicable. Cover this slice's errors, cleanup, and stale-result behavior where relevant; do not replace complete operations with previews.
- [ ] Update current documentation and the changelog for public behavior, and run the appropriate shared development checks. Preserve optional dependencies, logging/schema compatibility, and Python 3.10/3.13 endpoint contracts when typing or attribution changes.

## Coordination

The claimant owns this slice's behavior and tests. Before concurrent implementation, record owners for overlapping Investigation session, resource/job, execution, or native UI interfaces and name the implementer responsible for integration and test/import reconciliation. Coordinate shared-module edits without adding artificial blocking edges. Record the integration revision and verified editable environment when claiming the ticket.
