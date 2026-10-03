# 02: Remove legacy tools and transports

Status: claimed
Blocked by: none

**What to build:** Callers receive a query-focused tooling library rather than two parallel tooling routes. Retire legacy filtering, specialized tools, CLI, and MCP together with their obsolete tests, packaging, and current-use instructions, as authorized by the [specification](../spec.md).

- [ ] Remove Filters/Where and legacy query/Page/summary interfaces, specialized trace/tree/span/context/stats/failures/diff tools, field discovery/cache, rendering/validation tools, and tail/watch behavior.
- [ ] Remove CLI, completion, MCP, module-entry CLI dispatch, transport-only output schemas, and transport-only dependencies and extras.
- [ ] Public tooling exports retain query functionality and necessary errors; no aliases, forwarding modules, or legacy-to-IXR translation layer preserve the retired interfaces.
- [ ] Existing query-plan execution through both adapters remains verifiable. The Predicate facade needed by current plans remains only until ticket 03 replaces it.
- [ ] Retire tests protecting only deleted contracts. Port independently useful expression/source behavior from mixed test files to the retained query interface before deleting those cases.
- [ ] Remove transport-specific error presentation where unused. Leave cursor/source internals needed by the current source implementation for ticket 04 rather than prematurely breaking retained execution.
- [ ] Remove or clearly mark obsolete current-use documentation and examples at the time the interfaces disappear; provide a concise breaking-change notice. The complete documentation audit follows in ticket 05.
- [ ] Preserve the core log-record schema, typed package marker, core context/filter behavior, logging compatibility shims, and the core logging tests.
- [ ] Verify installed public imports, base installation without Polars, and representative retained query tests without transport dependencies.

## Implementation guidance

Deletion withdraws specialized reconstruction behavior; group-by is not a replacement for trace/tree reconstruction. Keep the remaining useful query semantics rather than rebuilding specialized tools in this ticket. Coordinate overlapping public-export edits with ticket 01 if work proceeds concurrently.
