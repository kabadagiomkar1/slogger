# 20: Reopen verified datasets and reclaim cache safely

**What to build:** Reopening verifies source contents before reusing completed
capture/index data, and resource controls reclaim only safe unused storage.

**Blocked by:** 06

**Status:** claimed

Type: task

Source: [Native IXR investigation TUI specification](../spec.md). This is a production slice of the approved native design; resolved prototype work is evidence, not its implementation.

- [ ] Verify current boundaries, ordered/repeated inputs, content changes even
  with unchanged size/mtime, versions, and corruption. A saved prefix followed
  by appends cannot count as the current complete dataset.
- [ ] Choose durable cache location/versioning and protect active datasets across
  processes. Recover stale ownership and clean expired/abandoned captures.
- [ ] Account for allocated capture/index/result/staging/journal/spill storage;
  expose usage, configurable budget/expiry, and protected clear controls.
- [ ] Default to provisional 10 GB managed disk and seven-day inactivity expiry;
  resource failures stay actionable. RAM browsing limits are configurable and
  distinct from total process memory. 24 selects a measured default.
- [ ] Verification/reuse progress is visible; cache reuse does not imply zero I/O.
- [ ] Keep reusable operations headless and explicitly scoped, with structured records, separate origins/status/diagnostics, bounded working storage, and unchanged IXR primitive semantics. TUI workflow and presentation state stay in the consumer; CLI/MCP transports remain outside this ticket.
- [ ] Add behavior tests through Investigation session operations using real JSONL inputs and an installed package, plus focused native interaction tests where applicable. Cover this slice's errors, cleanup, and stale-result behavior where relevant; do not replace complete operations with previews.
- [ ] Update current documentation and the changelog for public behavior, and run the appropriate shared development checks. Preserve optional dependencies, logging/schema compatibility, and Python 3.10/3.13 endpoint contracts when typing or attribution changes.

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
