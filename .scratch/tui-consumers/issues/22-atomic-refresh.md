# 22: Refresh without losing the latest investigation state

**What to build:** Explicit refresh captures separately while the old
investigation stays usable, then publishes a coherent replacement atomically.

**Blocked by:** 07, 15, 18, 19, 21

**Status:** resolved

Type: task

Source: [Native IXR investigation TUI specification](../spec.md). This is a production slice of the approved native design; resolved prototype work is evidence, not its implementation.

- [x] Reconcile main/independent filters, search/options, tree state, panes,
  preferences, and aggregate configuration edited during replacement capture.
  Reapply the latest active scopes before publication; no unfiltered flash.
- [x] Restore selection/pins only for verified identical source occurrences;
  changed, disappeared, or ambiguous identities produce explicit diagnostics.
- [x] Failed/canceled or over-budget refresh keeps the old complete dataset and
  result handles usable. Active plus replacement storage remains accounted.
- [x] Controlled interleavings demonstrate stale old jobs cannot publish into the
  new dataset, and unsuccessful staging is safely cleaned.
- [x] Keep reusable operations headless and explicitly scoped, with structured records, separate origins/status/diagnostics, bounded working storage, and unchanged IXR primitive semantics. TUI workflow and presentation state stay in the consumer; CLI/MCP transports remain outside this ticket.
- [x] Add behavior tests through Investigation session operations using real JSONL inputs and an installed package, plus focused native interaction tests where applicable. Cover this slice's errors, cleanup, and stale-result behavior where relevant; do not replace complete operations with previews.
- [x] Update current documentation and the changelog for public behavior, and run the appropriate shared development checks. Preserve optional dependencies, logging/schema compatibility, and Python 3.10/3.13 endpoint contracts when typing or attribution changes.

## Coordination

Ticket22 owns reusable staged replacement capture, verified occurrence restoration,
combined temporary/durable admission and native atomic adoption/reconciliation.
Keep headless APIs free of Textual/Rich; preserve complete IXR semantics and20/21
resource/lease/configuration contracts. Old and replacement storage must share total
admission even under no-cache. Actual owner/replacement generation protects queued
messages when verified reuse preserves dataset_id. Source occurrence/origin plus
captured bytes prove identity; application dictionaries, IDs or names do not.

Reconcile latest applied Main/independent scopes separately from pending requests
and newer drafts; requested grouping/metrics separately from retained result scopes.
Search, folds, panes, pins/selection and preferences may change during capture.
Required-stage failure/cancel preserves the old complete results. Publish native
owner/view/controller bindings together; settle completion/job readers before old
storage/lease release. Cleanup failures retain accounted leftovers and diagnostics.

15/18/19/21 are integrated prerequisite owners.22 is the sole remaining feature
implementer. The merger reconciles source, imports/tests/docs; later23 terminal and
24 scale validation may run concurrently. Ctrl+R/palette refresh preserves existing
F2–F10 and Ctrl+D routes. CLI/MCP transports, logging and CI remain outside scope.

Claimed against clean integration `9dac733`, with07/15/18/19/21 resolved. Own
prepared branch `codex/tui-22` reuses the clean completed06 worktree:
`/Users/omkar.kabadagi/.codex/worktrees/tui-06/slogger`. Verified own editable
interpreters: `/private/tmp/slogger-tui-06-env/bin/python` (3.13, registered) and
`/private/tmp/slogger-tui-06-py310/bin/python` (3.10), actual Polars/Textual present;
preflight verified at preparation `eaab141`. Merge latest integration before work,
reuse without reinstalling or repointing primary. Context pointers under
`/private/tmp/slogger-tui-implementation/`: context.md, refresh22-interface-map.md,
refresh-coordination-notes.md, ticket15/18/19/20/21-notes.md. Root reuses completed
`/root/implement_tui_15` as22 implementer; own22 checkout remains separate.

## Resolution

Implemented staged headless refresh, actual owner/request identity, raw captured
source-occurrence restoration and total active/replacement temporary admission.
Durable refresh reuses the existing cache catalog and leases. Shared configuration
validates all live owners atomically; new capture starts with the latest admitted
settings. Unpublished handles remain strongly owned until transfer or cleanup;
failed/partial cleanup retains observed accounting and permits retry.

Native Ctrl+R/palette refresh keeps the old complete investigation usable during
capture/staging. It stages latest applied Main/independent scopes, search/options,
complete tree, discovery and requested aggregates before one-turn atomic adoption.
Initial selected/pinned record reads are required staging, not post-publication IO.
Pending requests requeue independently of newer drafts; actual owner plus replacement
epoch rejects queued old messages even when durable dataset_id repeats. Selection,
pins and anchors restore through source occurrence and raw bytes. Semantic sparse
fold/focus and exact reveal state survive local tree IDs shifting, with bounded
working metadata. Latest panes/preferences remain in the native consumer. Reader
settlement precedes retired-owner storage/lease cleanup; failures stay accounted
and Ctrl+R retries cleanup first. Shutdown closes actual adopted ownership.

Feature source committed `cc123e3`; `6c1cf3b` changes only a filesystem fault-test
boundary to portable Path.open and requires an injection witness. Twenty-one new
headless/native refresh tests use installed APIs, real JSONL and controlled actual
source read, IPC, SQLite, initial-record read and deletion interleavings. Required
failure/cancel, raw identity, latest-state restaging, reused dataset owner, combined
budget and partial cleanup cases are covered. Current API/native/tooling/capability
documentation and changelog describe the public contracts.

Shared endpoint checks (actual Polars/Textual, verified own editable environments):
- Python 3.13.9 at `cc123e3`: docs/Ruff/Pyrefly green; **517 passed in 166.35s**.
- Python 3.10 at `6c1cf3b`: docs/Ruff/Pyrefly green; **517 passed in 171.32s**.
- The portable initial-read fault regression also passes independently on both.
  Production source is identical between those revisions; final additions are
  documentation/tracker only and shared fast checks pass.

Adopted integration `938f1b7`; final integration recheck has no newer source to merge.
Evidence logs and final API/resource/23/24 handoff are under
`/private/tmp/slogger-tui-implementation/`: `ticket22-check313-final.log`,
`ticket22-check310-portable-final.log`, and `ticket22-notes.md`.
No actual emulator/SSH/multiplexer or 1–5 GB/RSS/CPU qualification is claimed;
those remain separate ticket 23/24 validation.
