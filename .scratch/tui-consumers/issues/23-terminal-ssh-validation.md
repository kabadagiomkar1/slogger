# 23: Validate and harden real terminal and SSH interactions

**What to build:** The complete workflow has documented actual local/remote
terminal support and targeted fixes for reported interaction failures.

**Blocked by:** 22

**Status:** ready-for-agent

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

The claimant owns this slice's behavior and tests. Before concurrent implementation, record owners for overlapping Investigation session, resource/job, execution, or native UI interfaces and name the implementer responsible for integration and test/import reconciliation. Coordinate shared-module edits without adding artificial blocking edges. Record the integration revision and verified editable environment when claiming the ticket.
