# 12: Discover keys and values across the whole dataset

**What to build:** The same completion menu discovers every observed field
and scalar value, including rare late trace/span names and identifiers.

**Blocked by:** 11

**Status:** resolved

Type: task

Source: [Native IXR investigation TUI specification](../spec.md). This is a production slice of the approved native design; resolved prototype work is evidence, not its implementation.

- [x] Disk-backed discovery covers the complete investigation without sampling
  caps on lines, keys, or values. Progress/readiness is explicit.
- [x] Small prefix-matched pages, common-value ranking without a prefix, and
  narrowed prefixes make all observed scalar choices reachable.
- [x] Typed values and nested/literal paths insert with correct escaping. Stale
  discovery jobs cannot replace choices for a later dataset or prefix.
- [x] Discovery/result storage participates in disk accounting and keeps working
  memory bounded for high-cardinality data.
- [x] Keep reusable operations headless and explicitly scoped, with structured records, separate origins/status/diagnostics, bounded working storage, and unchanged IXR primitive semantics. TUI workflow and presentation state stay in the consumer; CLI/MCP transports remain outside this ticket.
- [x] Add behavior tests through Investigation session operations using real JSONL inputs and an installed package, plus focused native interaction tests where applicable. Cover this slice's errors, cleanup, and stale-result behavior where relevant; do not replace complete operations with previews.
- [x] Update current documentation and the changelog for public behavior, and run the appropriate shared development checks. Preserve optional dependencies, logging/schema compatibility, and Python 3.10/3.13 endpoint contracts when typing or attribution changes.

## Coordination

Ticket12 owns the complete disk-backed headless field/scalar discovery index and
paged prefix choices, plus dataset-aware publication into11's reusable completion
menu. Preserve `FilterCompletion` exact text/cursor/draft-generation/replacement
contract, typed JSON insertion and independent editor instances.13 owns search and
console highlights;16 owns aggregates and field targeting;14/15 own trees/context;
20 owns durable accounting/leases/external growth;21 later owns runtime resource
updates/settings. Reuse session lifecycle registries, explicit dataset scope and
managed allocation; do not import native policy into headless discovery.

Prefer discovery modules and additive editor/app hooks. The merger reconciles
shared imports, app composition/docs and native interactions. No file overlap adds
semantic graph blockers.19 will reuse the same complete discovery/editor behavior.

Claimed against integration `136298e`, with11 resolved and20 integrated. Worktree
`codex/tui-12`: `/Users/omkar.kabadagi/.codex/worktrees/tui-12/slogger`, prepared at
`f3fc4d8`; merge current integration before work. Verified editable interpreters:
`/private/tmp/slogger-tui-12-env/bin/python` (3.13, registered) and
`/private/tmp/slogger-tui-12-py310/bin/python` (3.10), actual Polars/Textual present.
Reuse them without reinstalling or repointing primary. Context pointers under
`/private/tmp/slogger-tui-implementation/`: context.md, execution-notes.md,
filter-search-aggregate-coordination.md, ticket11-notes.md and ticket20-notes.md.

## Resolution

Implemented complete dataset-scoped managed discovery with structured job/status/
index/page contracts. Mapping paths and typed scalar field values are discovered
across all verified records; separate supported immediate array-element observations
serve contains_any/contains_all without changing scalar equality/IN suggestions or
inventing array-index paths. Pages retain exact escaping, typed insertions, literal
prefix matching and frequency ranking. Scalar frequency counts record occurrences;
array frequency counts immediate supported elements, including repeated elements.
Unsupported empty components, nonfinite scalars and collection/nonfinite elements
have explicit guidance/counts. Working traversal/cache/page admission and SQLite
managed growth/ceiling/storage cleanup remain bounded; no sampling previews publish.

The reusable native editor binds an explicit DiscoveryIndex, uses one latest-only
background request, rejects stale/closed dataset or exact draft/cursor/generation
responses, and pages observed choices with PgUp/PgDn alongside syntax choices.
Native progress, cancel/retry and safe teardown preserve Main, JSON pins/focus,
count panes and search. No settings, refresh or transport workflow added ahead.

Verified own editable Python3.13.9 and3.10.20 environments, actual Textual8.2.8/
Polars1.44.2, with no reinstall or primary changes. Current integration99f19c7 is
an ancestor; final source/check revisiondd0df8e includes13/search and16/counts.
Full shared docs/Ruff/Pyrefly/pytest checks pass **449 tests on each endpoint**;
pytest73.15s/77.90s are suite wall times, not benchmarks. Logs are
`/private/tmp/slogger-tui-implementation/ticket12-check-handoff-py313.log` and
`ticket12-check-handoff-py310.log`; API/resource/native reuse details are in
`ticket12-notes.md` beside those logs.

Ten new real-file/native tests cover20,011records,20,010 unique identifiers,
1,200keys,40-level paths,12,000-character values, complete tiny pages, typed JSON,
literal%/_ prefixes, late rare values, cancellation/readiness/resource failure,
closed scopes, independent menus/paged/stale edits and immediate-array contexts.
Integration fixed13's OS fault fixture to target the purpose-named search worker
rather than every concurrent capture reader; all supersession/pin assertions remain.
Only OS open/delay is injected, with no internal widget/store/index mock. Current
API/native/ownership/capability/glossary/changelog docs are updated. Actual terminal,
SSH/clipboard/Linux and1–5GB/RSS/CPU qualification remain23/24 and are not claimed.
