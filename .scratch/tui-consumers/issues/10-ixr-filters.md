# 10: Apply the complete IXR filter language

**What to build:** An approachable infix editor produces exact paged filtered
views through shared IXR execution, with responsive, cancelable application.

**Blocked by:** 06

**Status:** ready-for-agent

Type: task

Source: [Native IXR investigation TUI specification](../spec.md). This is a production slice of the approved native design; resolved prototype work is evidence, not its implementation.

- [ ] Comparisons, structural equality, membership, array operators, substring,
  regex, starts_with, presence/missing, logger_prefix, parentheses, and boolean
  precedence retain the full current reference semantics.
- [ ] Nested and quoted literal-key paths, typed values, missing/null, and
  bool/number distinctions resolve without coercion or application-field aliases.
- [ ] Complete result delivery preserves origins and order with bounded working
  memory; existing QueryPlan execution remains compatible.
- [ ] Draft, applied, and pending state is clear. Enter applies; useful syntax/type
  errors, Esc cancellation, and stale completions preserve the successful view.
- [ ] Python is the reference default; optional native execution is only exposed
  explicitly with its existing capability/dependency errors and no fallback.
- [ ] Keep reusable operations headless and explicitly scoped, with structured records, separate origins/status/diagnostics, bounded working storage, and unchanged IXR primitive semantics. TUI workflow and presentation state stay in the consumer; CLI/MCP transports remain outside this ticket.
- [ ] Add behavior tests through Investigation session operations using real JSONL inputs and an installed package, plus focused native interaction tests where applicable. Cover this slice's errors, cleanup, and stale-result behavior where relevant; do not replace complete operations with previews.
- [ ] Update current documentation and the changelog for public behavior, and run the appropriate shared development checks. Preserve optional dependencies, logging/schema compatibility, and Python 3.10/3.13 endpoint contracts when typing or attribution changes.

## Coordination

The claimant owns this slice's behavior and tests. Before concurrent implementation, record owners for overlapping Investigation session, resource/job, execution, or native UI interfaces and name the implementer responsible for integration and test/import reconciliation. Coordinate shared-module edits without adding artificial blocking edges. Record the integration revision and verified editable environment when claiming the ticket.
