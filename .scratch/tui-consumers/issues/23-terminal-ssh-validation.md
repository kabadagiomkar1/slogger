# 23: Validate and harden real terminal and SSH interactions

**What to build:** The complete workflow has documented actual local/remote
terminal support and targeted fixes for reported interaction failures.

**Blocked by:** 22

**Status:** claimed

Type: task

Source: [Native IXR investigation TUI specification](../spec.md). This is a production slice of the approved native design; resolved prototype work is evidence, not its implementation.

- [ ] Exercise supported local terminals and SSH/multiplexer sessions for resize,
  mouse scrolling/panning, selection, paste/copy, focus/tab switching, and all
  keyboard fallbacks. Retain the reported Codex mouse case as unreproduced
  unless new evidence establishes a cause.
- [ ] Declare the tested platform/dependency/capability matrix and useful unavailable
  diagnostics. Headless or PTY checks are not substitutes for emulator/SSH evidence.
- [ ] No credentials, SSH host provisioning, or access permissions are assumed.
  Provide a reproducible manual exercise; if required environments are unavailable,
  record that validation as pending rather than claim it passed or silently close
  the requirement. Coordinate environment-dependent evidence with the user.
- [ ] Public installation/use guidance reflects the actual optional package setup
  and distribution naming constraints, with no identical-appearance claim.
- [ ] Keep reusable operations headless and explicitly scoped, with structured records, separate origins/status/diagnostics, bounded working storage, and unchanged IXR primitive semantics. TUI workflow and presentation state stay in the consumer; CLI/MCP transports remain outside this ticket.
- [ ] Add behavior tests through Investigation session operations using real JSONL inputs and an installed package, plus focused native interaction tests where applicable. Cover this slice's errors, cleanup, and stale-result behavior where relevant; do not replace complete operations with previews.
- [ ] Update current documentation and the changelog for public behavior, and run the appropriate shared development checks. Preserve optional dependencies, logging/schema compatibility, and Python 3.10/3.13 endpoint contracts when typing or attribution changes.

## Coordination

Ticket23 owns consumer terminal display/input hardening, focused native/render
regressions, portable demo/manual exercise, capability diagnostics and maintained
terminal guidance. Reproduce source ESC/DEL/C1 rendering and modified tree-wheel
behavior before targeted fixes; keep original record/search/field semantics exact.
The user's single `=` equality spelling may be added as a shared equality alias,
with Main/Scope completion and existing IXR semantics preserved. CLI/MCP, logging,
credentials, host provisioning and publication remain outside scope.

Ticket24 independently owns qualification runner/oracles, evidence and measured
resource defaults. Both may update native guidance/changelog; the merger reconciles
those files. Report any true shared-source fix before overlapping edits.23 owns
consumer/core filter spelling changes;24 reports correctness regressions to their
feature owner. Root coordinates checks so full endpoint runs do not compete with
large measurements. Actual terminal and scale evidence are independent.

Claimed against clean integration `ab949889` after22 resolved. Existing own branch
`codex/tui-23` uses `/Users/omkar.kabadagi/.codex/worktrees/tui-07/slogger`.
Verified own editable `/private/tmp/slogger-tui-07-env/bin/python` (registered3.13)
and `/private/tmp/slogger-tui-07-py310/bin/python` (3.10), actual Polars/Textual;
both preflight reverified before claim. Merge latest integration before work,
reuse without reinstalling or repointing primary. Reused implementer
`/root/implement_tui_19`; this is distinct from its completed19 checkout.

Context: `/private/tmp/slogger-tui-implementation/` ticket22-notes.md,
terminal23-preparation.md, terminal23-control-map.md, terminal23-demo.py,
frontier23-24-coordination.md, execution-notes.md. User will run the production
terminal/SSH checklist. Publish a concrete tested portable exercise; retain required
actual combinations as pending until reported, distinguishing headless and PTY.
Do not retry prior denied native Terminal app access. Root requests the user's
result report when the hardening build/checklist is ready. Keep ticket claimed
while required external evidence remains pending; do not silently resolve it.
