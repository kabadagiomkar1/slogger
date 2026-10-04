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
- [x] Declare the tested platform/dependency/capability matrix and useful unavailable
  diagnostics. Headless or PTY checks are not substitutes for emulator/SSH evidence.
- [x] No credentials, SSH host provisioning, or access permissions are assumed.
  Provide a reproducible manual exercise; if required environments are unavailable,
  record that validation as pending rather than claim it passed or silently close
  the requirement. Coordinate environment-dependent evidence with the user.
- [x] Public installation/use guidance reflects the actual optional package setup
  and distribution naming constraints, with no identical-appearance claim.
- [x] Keep reusable operations headless and explicitly scoped, with structured records, separate origins/status/diagnostics, bounded working storage, and unchanged IXR primitive semantics. TUI workflow and presentation state stay in the consumer; CLI/MCP transports remain outside this ticket.
- [x] Add behavior tests through Investigation session operations using real JSONL inputs and an installed package, plus focused native interaction tests where applicable. Cover this slice's errors, cleanup, and stale-result behavior where relevant; do not replace complete operations with previews.
- [x] Update current documentation and the changelog for public behavior, and run the appropriate shared development checks. Preserve optional dependencies, logging/schema compatibility, and Python 3.10/3.13 endpoint contracts when typing or attribution changes.

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

## Implementation progress

The completed code chunk hardens source controls at display/input/diagnostic
boundaries while retaining original records, exact typed path/value semantics,
lossless JSON copying and decoded search offsets. Focused native real-JSONL tests
reproduce control-sequence rendering, generated insertions, literal draft cursor/
click positions, modified wheel routing and panned highlights. The user's `=`
spelling is an additive shared typed equality alias with Main/Scope completion.

The maintained [terminal exercise](../../../docs/terminal-validation.md) and
[stdlib generator](../../../examples/investigation_demo.py) provide independent
64-record totals, a verified append-once refresh marker, failure/retry/restoration
steps, keyboard fallbacks and separate OSC 52 sent/accepted reporting. A tracked
source archive and exact revision/digest can be transferred using existing SSH
without publishing this local integration branch.

Status remains **claimed**: the user will run the reviewed actual local/SSH/
multiplexer checklist. Actual platform/gesture/clipboard evidence and any resulting
reported fixes are pending; headless and PTY checks cannot close those requirements.
Verified source/tests revision `b6754667338ecc98cde8b2c309d635901a1f9cc3`:
shared docs/lifecycle, Ruff, Pyrefly and **527 tests passed on each of CPython
3.10.20 and 3.13.9**, actual Textual 8.2.8 and Polars 1.44.2. POSIX PTY smoke on
that revision sent stream/JSON/pin/tree keys, resized 150×34 → 65×30 → 150×34,
retained a live process and exited 0; it is transport evidence only. Demo/oracle,
ASCII and append/overwrite guards passed on both interpreters. Base-only imports
and missing-extra diagnostics remain verified; no optional installs/repointing.
Logs and exact interface/evidence handoff: outside-repo
`/private/tmp/slogger-tui-implementation/ticket23-notes.md`.

The final evidence/API prose commit changes no production source/tests. Actual
local emulator, Linux, SSH/multiplexer, delivered gestures and clipboard acceptance
are still pending the user report. No denied native Terminal access was retried.
