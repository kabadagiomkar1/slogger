# 10: Apply the complete IXR filter language

**What to build:** An approachable infix editor produces exact paged filtered
views through shared IXR execution, with responsive, cancelable application.

**Blocked by:** 06

**Status:** claimed

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

Owns shared infix parsing/path spelling and IXR-to-captured-view execution,
explicit view/job scopes, query cancellation, and the native Main filter editor.
Ticket07 owns capture lifecycle and bounded writer/resource admission; preserve
those contracts. Use its final notes before reconciling session close/readiness.
Ticket08 owns console navigation/presentation;09 inspector/pin/field targets.
The filter view must preserve dataset ordinal identity alongside result positions.
General QueryPlan execution stays compatible. Read execution-notes.md, including
regex isolation and typed/nested paths; no regex semantics change for responsiveness.

App compose, bindings, selection and imports overlap; each behavior owns its own
module/handler and merger agents reconcile all completed slices. Shared docs and
native tests retain all assertions. File overlap does not add blocking edges.

Prepared integration baseline: `06f8d03` on `codex/ixr-native-tui`.
Prepared isolated worktree: `/Users/omkar.kabadagi/.codex/worktrees/tui-10/slogger`.
Verified editable Python3.13: `/private/tmp/slogger-tui-10-env/bin/python`.
Verified editable Python3.10: `/private/tmp/slogger-tui-10-py310/bin/python`.
Both endpoint preflights passed. Claim and merge the latest integration branch
before implementation starts; merge it again before reporting completion.

Research pointers are under `/private/tmp/slogger-tui-implementation/`.

Claimed for implementation from integration `048dcca`; the prepared branch
will merge the latest integration before starting. Both endpoint environments
remain verified against its own isolated checkout.
