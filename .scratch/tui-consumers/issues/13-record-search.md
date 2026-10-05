# 13: Search filtered records with live highlighting

**What to build:** Literal text search highlights as the user types and
navigates matching records inside the applied Main filter without filtering them.

**Blocked by:** 10

**Status:** resolved

Type: task

Source: [Native IXR investigation TUI specification](../spec.md). This is a production slice of the approved native design; resolved prototype work is evidence, not its implementation.

- [x] Console/full-record scopes use complete decoded names/values, including
  hidden metadata in full scope; serialization escapes do not become matches.
- [x] Case and Unicode whole-word options, immediate highlights, no typing-driven
  cursor movement, complete background record counts, and next/previous/wrap
  navigation are usable with clear option states.
- [x] Changing scope, case, word options, or console-field visibility recomputes
  visible highlights and the complete match set, superseding prior work.
- [x] Empty search clears matches. Filter/request changes invalidate stale match
  scopes; cancellation and pending status preserve the prior successful view.
- [x] The complete match index is paged/disk-backed and resource-accounted.
- [x] Keep reusable operations headless and explicitly scoped, with structured records, separate origins/status/diagnostics, bounded working storage, and unchanged IXR primitive semantics. TUI workflow and presentation state stay in the consumer; CLI/MCP transports remain outside this ticket.
- [x] Add behavior tests through Investigation session operations using real JSONL inputs and an installed package, plus focused native interaction tests where applicable. Cover this slice's errors, cleanup, and stale-result behavior where relevant; do not replace complete operations with previews.
- [x] Update current documentation and the changelog for public behavior, and run the appropriate shared development checks. Preserve optional dependencies, logging/schema compatibility, and Python 3.10/3.13 endpoint contracts when typing or attribution changes.

## Coordination

Ticket13 owns headless decoded literal-text matching and bounded complete match
indexes, plus native compact search controls, console highlighting, navigation
and search-generation app hooks. Headless search receives explicit projection
options for the console field set; it must not import Textual/Rich or native
consumer defaults.11 owns reusable FilterEditor/menu/context;16 owns console/JSON
field targets and the lower aggregate pane;14 owns native/headless trees;15 later
joins search/filter results with ancestor context.20 owns durable global storage,
leases and admission. Preserve10 scopes, input leases and session-close registry.

Prefer feature modules and additive console/app hooks. The merger reconciles
shared imports, rendering/CSS, docs/changelog and combined interaction tests;
file overlap introduces no additional semantic blocker.

Claimed against integration `f3fc4d8` after10 resolved. Worktree `codex/tui-13`:
`/Users/omkar.kabadagi/.codex/worktrees/tui-13/slogger`; prepared at `ee7cfc8`,
merge latest integration before work. Verified editable endpoint environments:
`/private/tmp/slogger-tui-13-env/bin/python` (3.13, registered) and
`/private/tmp/slogger-tui-13-py310/bin/python` (3.10), with actual Polars/Textual.
Reuse them; do not reinstall or repoint primary. Pointers outside repository:
`/private/tmp/slogger-tui-implementation/context.md`, `execution-notes.md`,
`filter-search-aggregate-coordination.md` and `ticket08/10/14-notes.md`.


## Resolution

Implemented decoded literal search through `Investigation.search`: explicit dataset/
view/projection/request scopes, Unicode casefold and whole-word matching, complete
record counts, managed disk membership, bounded original pages, ordinal navigation
with wrap, input leases, cancellation and coherent failure/cleanup status. Missing
terminal imports/defaults keep these operations reusable by later CLI/MCP consumers.
Names and distinct decoded leaves never acquire serialization-escape or artificial
cross-leaf matches. Repeated input occurrences preserve original identities/origins.

Native Find offers F7 focus, Enter/Shift+Enter and F8/Shift+F8 navigation, keyboard/
mouse scope/case/word controls, immediate semantic console/full-JSON highlights,
150ms background debounce and generation-safe cancellation. Only visible viewport
ranges add highlight styling. Typing keeps record selection and independent pins;
Main requests invalidate matches until their retained/applied scope is ready.
Console visibility changes recompute; empty search clears. Integrated16 field
metadata, counts shortcuts/pane/focus,11 completion and14 tree behavior remain intact.
Tree/filter/search ancestor context remains15, explicitly labeled unavailable here.

Prepared ancestry confirmed, b15df86 adopted before implementation; latest761026d
(includes11/14/16/20) merged and reconciled in1ef8876 before final verification.
Own installed3.13.9 and3.10.20 environments were reused, with actual Polars1.44.2 and
Textual8.2.8. Both shared checks passed docs, Ruff, Pyrefly and **439 tests each**
against1ef8876; final tracker docs/fast checks passed. Ten new tests at approved
Investigation/native seams cover decoded nested names/scalars/quotes/backslashes/
newlines, Unicode words/expansions, late complete24,114 repeated occurrences,
projection/duration/span fallback policy, paging/count-versus-occurrence/navigation,
leases/readiness, actual disk admission/cancellation/OS removal errors, deterministic
stale work, mouse/keyboard options, pins, Main-pending regex cancellation, JSON/live
highlight consistency and highlighted-field aggregate targeting. Filesystem delay/
removal failure alone is injected at external boundaries; no owned matcher/index/
widget collaborator is mocked. Native integration regression suite also passed.

Current API, native guide, ownership/capability docs and changelog were updated.
No actual emulator/SSH/multiplexer, clipboard acceptance, Linux or1–5GB/RSS/CPU
qualification is claimed;23/24 retain those obligations. Full check logs and API/
merger notes are outside the repository in `/private/tmp/slogger-tui-implementation`.
