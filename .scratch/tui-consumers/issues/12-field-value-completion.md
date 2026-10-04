# 12: Discover keys and values across the whole dataset

**What to build:** The same completion menu discovers every observed field
and scalar value, including rare late trace/span names and identifiers.

**Blocked by:** 11

**Status:** claimed

Type: task

Source: [Native IXR investigation TUI specification](../spec.md). This is a production slice of the approved native design; resolved prototype work is evidence, not its implementation.

- [ ] Disk-backed discovery covers the complete investigation without sampling
  caps on lines, keys, or values. Progress/readiness is explicit.
- [ ] Small prefix-matched pages, common-value ranking without a prefix, and
  narrowed prefixes make all observed scalar choices reachable.
- [ ] Typed values and nested/literal paths insert with correct escaping. Stale
  discovery jobs cannot replace choices for a later dataset or prefix.
- [ ] Discovery/result storage participates in disk accounting and keeps working
  memory bounded for high-cardinality data.
- [ ] Keep reusable operations headless and explicitly scoped, with structured records, separate origins/status/diagnostics, bounded working storage, and unchanged IXR primitive semantics. TUI workflow and presentation state stay in the consumer; CLI/MCP transports remain outside this ticket.
- [ ] Add behavior tests through Investigation session operations using real JSONL inputs and an installed package, plus focused native interaction tests where applicable. Cover this slice's errors, cleanup, and stale-result behavior where relevant; do not replace complete operations with previews.
- [ ] Update current documentation and the changelog for public behavior, and run the appropriate shared development checks. Preserve optional dependencies, logging/schema compatibility, and Python 3.10/3.13 endpoint contracts when typing or attribution changes.

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
