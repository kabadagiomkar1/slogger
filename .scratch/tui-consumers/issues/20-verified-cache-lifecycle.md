# 20: Reopen verified datasets and reclaim cache safely

**What to build:** Reopening verifies source contents before reusing completed
capture/index data, and resource controls reclaim only safe unused storage.

**Blocked by:** 06

**Status:** resolved

Type: task

Source: [Native IXR investigation TUI specification](../spec.md). This is a production slice of the approved native design; resolved prototype work is evidence, not its implementation.

- [x] Verify current boundaries, ordered/repeated inputs, content changes even
  with unchanged size/mtime, versions, and corruption. A saved prefix followed
  by appends cannot count as the current complete dataset.
- [x] Choose durable cache location/versioning and protect active datasets across
  processes. Recover stale ownership and clean expired/abandoned captures.
- [x] Account for allocated capture/index/result/staging/journal/spill storage;
  expose usage, configurable budget/expiry, and protected clear controls.
- [x] Default to provisional 10 GB managed disk and seven-day inactivity expiry;
  resource failures stay actionable. RAM browsing limits are configurable and
  distinct from total process memory. 24 selects a measured default.
- [x] Verification/reuse progress is visible; cache reuse does not imply zero I/O.
- [x] Keep reusable operations headless and explicitly scoped, with structured records, separate origins/status/diagnostics, bounded working storage, and unchanged IXR primitive semantics. TUI workflow and presentation state stay in the consumer; CLI/MCP transports remain outside this ticket.
- [x] Add behavior tests through Investigation session operations using real JSONL inputs and an installed package, plus focused native interaction tests where applicable. Cover this slice's errors, cleanup, and stale-result behavior where relevant; do not replace complete operations with previews.
- [x] Update current documentation and the changelog for public behavior, and run the appropriate shared development checks. Preserve optional dependencies, logging/schema compatibility, and Python 3.10/3.13 endpoint contracts when typing or attribution changes.

## Coordination

Owns durable cache catalog/manifest, source and cache verification, process-safe
leases, expiry/clear, global allocation accounting and cache-aware session open.
Preserve07's bounded writer, data/index publication, source verification, prefix
failure and close contracts; extend admission without restoring per-record scans.
Read ticket07-notes.md and cache-trace-notes.md in the shared notes directory.
10 owns filter jobs and scoped result files,14 tree indexes/jobs; coordinate global
admission and session close with them directly. Headless imports stay stdlib-only.
Native edits are cache/reuse progress and launcher options; preserve09 inspector
pins and08 console options. Merger agents reconcile shared app, docs, exports/tests.
No artificial blocker is added for shared-file overlap.

Integration claim baseline: `eabfa9a` on `codex/ixr-native-tui`.
Prepared worktree: `/Users/omkar.kabadagi/.codex/worktrees/tui-20/slogger`.
Verified editable3.13: `/private/tmp/slogger-tui-20-env/bin/python`.
Verified editable3.10: `/private/tmp/slogger-tui-20-py310/bin/python`.
Both endpoint preflights passed. Merge latest integration before implementation
starts and again before final completion.07/09 are complete and queued for merge;
root will dispatch20 after that integration to keep storage ownership coherent.
Research pointers: `/private/tmp/slogger-tui-implementation/`.


## Resolution

Implemented durable versioned cache manifests/catalog admission, current opening
extent and per-occurrence source hashes, captured data/index hashes, authenticated
manifest checks, current resource admission on reuse, and visible verification I/O.
The native launcher uses an explicit durable default; headless callers opt in with
`cache_dir`. Complete captures retain stable dataset IDs while each reopened session
owns independent job storage. Failed/canceled prefixes remain session-only.

POSIX kernel leases protect active datasets across processes. Recovery reclaims
unregistered/abandoned staging and crashed job files/reservations; seven-day expiry
and explicit clear return structured protected/removed/reclaimed usage outcomes.
Global admission includes allocated blocks/logical bytes, directories, catalog
headroom, jobs, SQLite staging/sidecars and bounded writer reservations. Preserved
07 publication/rollback,10 operation/view lifecycle,14 external-growth ceilings and
close-before-remove contracts. Reuse publication is atomic with paged reads.

Merged integration through `c8d1001` (code baseline includes14 at `f3fc4d8`), removing
auto-merged duplicate external-growth/close gates. Final shared checks passed docs,
Ruff, Pyrefly and **410 tests on both Python3.10 and3.13** against the merged source.
Installed launcher help passed with cache/expiry/temporary flags. Tests use real
owned temporary caches, subprocess leases/reservations and actual SQLite staging;
focused native verification/reuse/cancellation cases pass. No installations,
primary editable changes, actual emulator/SSH/multiplexer or1–5GB/RSS claims.

API/runtime-settings handoff and complete evidence:
`/private/tmp/slogger-tui-implementation/ticket20-notes.md`.
