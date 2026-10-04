# 24: Qualify 1–5 GB investigations and choose resource defaults

**What to build:** Reproducible measurements establish the production resource
envelope and RAM default for complete 1 GB and 5 GB investigations.

**Blocked by:** 22

**Status:** claimed

Type: task

Source: [Native IXR investigation TUI specification](../spec.md). This is a production slice of the approved native design; resolved prototype work is evidence, not its implementation.

- [ ] Representative 100–200 MB files include custom/sparse/nested fields, long
  messages, cross-file traces, and high-cardinality groups. Record revision,
  input identity, machine, and cold/warm OS-cache conditions.
- [ ] Measure first browseable/complete opening, verified reuse cost, filters,
  search, completion, trees, aggregates, idle/active CPU, peak RSS, and total/
  peak disk including refresh staging. Account for failures under 10 GB honestly.
- [ ] Verify bounded working memory beyond browsing-cache admission; select and
  document a practical RAM default and admitted-record/resource envelope.
- [ ] Existing prototype timings are historical. No invented latency/CPU guarantees
  or sampled results replace required correctness. Correctness regressions are
  addressed in their owning slices rather than hidden behind qualification.
- [ ] Terminal validation and scale qualification can run concurrently; neither
  is a semantic prerequisite for the other's independent evidence.
- [ ] Keep reusable operations headless and explicitly scoped, with structured records, separate origins/status/diagnostics, bounded working storage, and unchanged IXR primitive semantics. TUI workflow and presentation state stay in the consumer; CLI/MCP transports remain outside this ticket.
- [ ] Add behavior tests through Investigation session operations using real JSONL inputs and an installed package, plus focused native interaction tests where applicable. Cover this slice's errors, cleanup, and stale-result behavior where relevant; do not replace complete operations with previews.
- [ ] Update current documentation and the changelog for public behavior, and run the appropriate shared development checks. Preserve optional dependencies, logging/schema compatibility, and Python 3.10/3.13 endpoint contracts when typing or attribution changes.

## Coordination

Root's confirmed final review batch is assigned to24 as a single fix owner:
Filter/Search constructor and monitor independent borrowed-input cleanup;
runtime-compatible durable capture admission and defensive first-record paging;
atomic native refresh staging/publication under obsolete-search cleanup faults;
current delivery documentation and consumer-only named aggregate requests;
native Main/independent/aggregate retirement failure retention and explicit retry,
including retryable AggregateResult deletion.
Ticket24 owns the real near-limit dense-container native performance correction
in tui/presentation.py and any proven secondary rendering cost; preserve full body,
control/tab/newline search mapping, targeting and no renderer/result caps.
Shared files include session.py, filters.py, search.py, tui/app.py, refresh.py,
filter_editor.py and tree.py plus their real-file/native regression tests. Root and
merger remain read-only; preserve the separate23 control-spelling changes.


Ticket24 additionally owns the measured SQLite accounting-window correction in
`investigation/resources.py`, discovery `_write`/build scheduling, and equivalent
tree/aggregate write scheduling where exact reads permit batching. Preserve global
durable admission, engine ceilings, sidecars, cancellation and owner cleanup.
Ticket23 owns query insertion spelling in `discovery.py` and `core/encoding.py`;
merge23 first and preserve that distinct change. Root/merger remain read-only on
these accounting modules until24 reports its tested correction.

Ticket24 owns reproducible benchmark runner, independent streamed correctness
oracles, measurement artifacts, admitted-record/resource-envelope checks and
measured RAM defaults. Use full1GB/5GB inputs; no sampled complete operations,
preview/group caps or invented latency/CPU thresholds. Normal10GiB refusals are
recorded with old-owner usability before distinct higher-budget characterization.
Measure worker-aware CPU/RSS, allocated/reserved managed disk including overlap,
and cold application-cache versus verified reuse with uncontrolled OS-cache state.

Ticket23 owns terminal consumer and shared filter spelling hardening. Both may
update native guidance/changelog; merger reconciles docs. Report correctness
regressions with a focused reproduction to the feature owner. Propose shared
resource-default changes explicitly and rerun relevant measurements. Root
coordinates checks and pinned revisions so endpoint tests do not compete with
large measurements. Actual user terminal/SSH evidence does not block independent
scale work; native headless timings are separate from emulator evidence.

Claimed against clean integration `ab949889` after22 resolved. Existing own branch
`codex/tui-24` uses `/Users/omkar.kabadagi/.codex/worktrees/tui-08/slogger`.
Verified own editable `/private/tmp/slogger-tui-08-env/bin/python` (registered3.13)
and `/private/tmp/slogger-tui-08-py310/bin/python` (3.10), actual Polars/Textual;
both preflight reverified before claim. Merge latest integration before work,
reuse without reinstalling or repointing primary. Reused implementer
`/root/qualification_fixture_prep`; outside preparation is not qualification.

Context: `/private/tmp/slogger-tui-implementation/` ticket22-notes.md,
fixture-prep-notes.md, qualification-plan.md, qualification-machine.json,
scale-fixtures/{manifest.json,README.md,generate_fixtures.py,files-1gb.txt,
files-5gb.txt}, frontier23-24-coordination.md; outside prepared runner/oracles and
notes in `/private/tmp/slogger-qualification24-prep/`. Actual tiny process sampling
recovered through authorized task profiling; no continuing permission blocker.
Final API reconciliation, full application oracles, refusal/cleanup and near-limit
encoded/decoded admission checks remain required. Preserve input hashes until
concise durable evidence, then clean task-owned large inputs/results.
