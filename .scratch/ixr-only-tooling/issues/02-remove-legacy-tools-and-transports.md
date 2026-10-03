# 02: Remove legacy tools and transports

Status: resolved
Blocked by: none

**What to build:** Callers receive a query-focused tooling library rather than two parallel tooling routes. Retire legacy filtering, specialized tools, CLI, and MCP together with their obsolete tests, packaging, and current-use instructions, as authorized by the [specification](../spec.md).

- [x] Remove Filters/Where and legacy query/Page/summary interfaces, specialized trace/tree/span/context/stats/failures/diff tools, field discovery/cache, rendering/validation tools, and tail/watch behavior.
- [x] Remove CLI, completion, MCP, module-entry CLI dispatch, transport-only output schemas, and transport-only dependencies and extras.
- [x] Public tooling exports retain query functionality and necessary errors; no aliases, forwarding modules, or legacy-to-IXR translation layer preserve the retired interfaces.
- [x] Existing query-plan execution through both adapters remains verifiable. The Predicate facade needed by current plans remains only until ticket 03 replaces it.
- [x] Retire tests protecting only deleted contracts. Port independently useful expression/source behavior from mixed test files to the retained query interface before deleting those cases.
- [x] Remove transport-specific error presentation where unused. Leave cursor/source internals needed by the current source implementation for ticket 04 rather than prematurely breaking retained execution.
- [x] Remove or clearly mark obsolete current-use documentation and examples at the time the interfaces disappear; provide a concise breaking-change notice. The complete documentation audit follows in ticket 05.
- [x] Preserve the core log-record schema, typed package marker, core context/filter behavior, logging compatibility shims, and the core logging tests.
- [x] Verify installed public imports, base installation without Polars, and representative retained query tests without transport dependencies.

## Implementation guidance

Deletion withdraws specialized reconstruction behavior; group-by is not a replacement for trace/tree reconstruction. Keep the remaining useful query semantics rather than rebuilding specialized tools in this ticket. Coordinate overlapping public-export edits with ticket 01 if work proceeds concurrently.

## Resolution

Removed the legacy filtering/tool cluster, CLI/completion/module dispatch, MCP, transport schema and schema checker, and argcomplete extras. Public exports now expose retained query plans, builders, reductions, and ToolError; the temporary Predicate facade and private Reader/cursor internals remain for tickets 03/04. Removed unused ToolError transport serialization. Only the root logging module documentation changed; logging code and core schemas remain unchanged.

Migrated typed matching assertions to public query execution, replaced legacy-query/cursor oracles with source-order/decoding expectations, preserved core logging review regressions and source/time-merge/limit cases, and retired tests for withdrawn specialized behavior and transports. Removed current CLI docs and recipes, marked historical legacy designs as superseded, and added the breaking-change notice. Final documentation audit remains ticket 05.

Confirmed baseline ancestry and merged the completed runtime/backend prefactor from the integration branch before final validation. Validation on Python 3.13.9 / Polars 1.44.2: 301 retained tests pass; Ruff passes; Pyrefly reports zero errors (37 suppressed); diff check passes. A separate editable base-only environment verifies Python query execution without Polars or argcomplete, explicit dependency_missing for native execution, absent retired modules/extras, retained py.typed and core log-record schema, and removed transport schema. Python 3.10 and built-wheel verification follow in ticket 06.
