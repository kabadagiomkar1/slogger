Repository review — 2026-09-28

The review covered the logging core, configuration and context lifecycle, formatters,
record schemas, tools, CLI, completion, MCP adapter, packaging configuration, tests,
examples, README and API/CLI documentation. Plans were used to distinguish intended
contracts from current behavior; deferred features were not implemented.

## Resolution — 2026-09-29

All eleven findings below are addressed. The follow-up adds regression coverage
for callback/nested-emission deadlocks, logging-control span fields, aggregate
filters and grouping, stdin replay, cyclic parents, timestamp ordering, bounded
collector state, typed field identities, cache races, MCP framing/arguments, and
schema rejection. Normal-path behavior and caller attribution remain covered on
Python 3.10 and 3.13. Callback reconfiguration now raises `RuntimeError`;
MCP uses the standard newline transport and rejects stdin log sources.

Follow-up validation: **273 tests pass** with `-W error` on both Python 3.10
and 3.13. Ruff passes; Pyrefly at warning severity reports zero diagnostics
(23 existing suppressions). `git diff --check` passes. The follow-up adds 24
regression cases without skips, xfails, or new type suppressions.

The original review below is historical: file/line references and validation
counts describe commit `8d53bf3`, before this follow-up. Its outstanding-findings
and stdin/MCP limitation statements are superseded by this resolution.

**Original findings, now resolved, ordered by impact**

1. **[P1] Logging callbacks can deadlock configuration.**
   `src/slogger/config.py:44` and `:179`: an `emit()` callback calling `configure()`
   waits for the emission gate's reader count to reach zero, including its own
   active log call. Reproduced in a subprocess that did not return within one
   second and was terminated. Nested logging can also wait behind a queued
   writer while the outer emission holds a reader slot. Track per-thread read
   depth and either reject configuration from emission callbacks before acquiring
   `_lock`, or design a deferred configuration operation. Add bounded subprocess
   tests so regressions cannot hang pytest.

2. **[P1] The advertised MCP server does not speak standard stdio framing.**
   `src/slogger/tools/mcp/__init__.py:378`: newline-delimited `ping` input produces
   a response beginning `Content-Length: 41`. The declared protocol version's
   [official transport specification](https://modelcontextprotocol.io/specification/2024-11-05/basic/transports)
   requires newline-delimited JSON-RPC. Standard clients cannot parse this response.
   The existing `test_serve_newline_protocol` explicitly asserts the incompatible
   header, so it validates the implementation rather than interoperability.
   Use standard framing by default; retain legacy framing only as an explicit
   compatibility mode if required. `_read_message` also treats a byte length as
   a character count, which can block on unescaped non-ASCII framed payloads.

3. **[P1] Span context can turn a successful operation into an exception.**
   `src/slogger/span.py:190` and `:202`: `_emit_end` expands user fields alongside
   explicit `stacklevel` / `exc_info` arguments. Under `capture_logs()`,
   `with get_logger().span("x", stacklevel="field"): pass` raises `TypeError`
   on exit. An `@instrument` capture with one of these parameter names has the
   same problem; an exception path can mask the application's original error.
   Carry span context separately from stdlib logging control arguments, preserving
   the documented merge order and caller attribution on both Python versions.

4. **[P1] Span statistics ignore requested span/window constraints.**
   `src/slogger/tools/stats.py:392` and `:435`: selection removes `Filters.span`
   and never applies it to reconstructed nodes. `stats("tests/fixtures/logs/trace.log",
   spans=True, filters=Filters(span="charge"))["totals"]["spans"]` returns **5**,
   including unrelated spans. A span starting on September 1 and ending on
   September 28 is counted with `since=September 27`, despite the planned
   start-else-end anchor rule. Apply name and anchor-window checks when accumulating
   nodes. `failures()` likewise removes the span predicate without applying a
   replacement. Add focused API and CLI tests for these filters.

5. **[P1] Multi-pass stdin tools lose records and can return incorrect IDs.**
   `src/slogger/tools/trace.py:333` and `src/slogger/tools/context.py:82`:
   `trace("-", trace_id="aaaa")` consumes stdin while selecting, then reconstructs
   zero spans. `context("-", record_id="-:3", before=0, after=0)` reads the
   remainder on its second pass, restarts numbering at `-:1`, and can discard rows
   as duplicate IDs. Reproduced with six same-trace records. Spool stdin once with
   stable physical-line labels and replay it for both passes. The docs now state
   the current limitation instead of promising reliable stdin reconstruction.

6. **[P2] Reconstruction silently loses cyclic spans and sorts timestamps as text.**
   `src/slogger/tools/trace.py:213`: a self-parented span becomes its own child and
   never reaches the root list; longer parent cycles are also omitted. Detect
   cycles and report an orphan/root plus a warning. `:93` also orders timestamps
   lexicographically, unlike `Reader`'s UTC-normalized comparison. Mixed offsets
   or precision can reverse logs in a waterfall. Share the parsed timestamp sort
   policy while retaining stable input-order ties.

7. **[P2] Span aggregation retains all ordinary records despite `keep_logs=False`.**
   `src/slogger/tools/spans.py:57`: `_select_only` stores a full copy of every
   non-event record. A trace with millions of ordinary logs therefore has memory
   proportional to the entire input. `_skipped`, tree group metadata, and stats
   group metadata can also grow after the advertised group cap is reached.
   Evaluate selection during ingestion and retain one selection bit per tracked
   group. Keep exact omitted-group accounting separate from bounded reconstruction
   state. This is the largest tooling memory optimization opportunity.

8. **[P2] Grouped span stats can split one span into multiple spans.**
   `src/slogger/tools/stats.py:414`: records are grouped before reconstruction.
   If a grouping field changes between `span.start` and `span.end`, the lifecycle
   is split into an unfinished span and a missing-start span in different groups.
   The stored `start_record` / `end_record` fields are not used for attribution.
   Reconstruct by trace/span identity first, then assign the group from the start
   record, falling back to the end record. Add a changed-context fixture.

9. **[P2] Field discovery merges distinct JSON values.**
   `src/slogger/tools/fields.py:41`: counters and distinct sets use raw values or
   JSON strings as keys. `True` and `1` share a key, as do `[]` and the literal
   string `"[]"`. Reproduced top counts of two instead of four distinct values.
   Use a typed internal identity while keeping existing display values. Also,
   `:299` records file identity after scanning: an append during the scan can
   associate an incomplete payload with the new identity. Cache only when the
   pre-scan and post-scan identities agree, and use unique temporary cache files
   for concurrent writers.

10. **[P2] MCP tool schemas do not describe their arguments.**
    `src/slogger/tools/mcp/__init__.py:269`: every tool advertises only `sources`,
    `filters`, and `order`, with no required arguments. `watch` actually needs
    `path`; `context` needs `record_id`; `diff` needs `before` and `after`.
    Publish per-tool schemas and required lists. Reject `"-"` sources through MCP:
    the process's stdin is already the protocol stream. Validate malformed
    request shapes so JSON arrays/scalars cannot terminate the server.

11. **[P2] Output validation is weaker than its published top-level contract.**
    `src/slogger/tools/output_schema.py:227`: `schema_version=True` is accepted as
    version 1. Numerous collection/string properties are not checked at all.
    The current fixture tests validate successful output only; they cannot
    establish parity with the JSON schemas. Add negative cases per property type
    and align the supported validator subset with the public docstring. The core
    log-record schema's required keys and property names do align with `schema.py`.

**Fixes and cleanups in the original review commit**

| Area | Correction | Regression coverage |
| --- | --- | --- |
| Development setup | `.[dev]` includes argcomplete, required by completion tests and type checking | Both fresh editable environments run the entire suite |
| Reconfiguration | Failed attachment restores prior logger state, filters, handlers and span-event setting; owned file handles remain usable | Failed custom attachment with a real JSON file; reused owned handler closes on reset |
| Serialization | Cycles, unsupported dict keys and broken `repr` preserve the record and unaffected fields | Both formatters and JSON field retention |
| Paging | Truncation preserves `_id`; `last` polling preserves time cursors; nonmatching records advance polling cursors | Resume and no-match tests |
| One-shot sources | Cache eligibility does not consume generators; validation reuses resolved inputs | Bare/nested generators and invalid generator records |
| Tailing | Stdin yields before the next read; explicit cursor overrides default backlog; incomplete final records are held back | Streaming sentinel, cursor and newline tests |
| Watch | Stdin IDs count physical lines, including skipped input | Blank, malformed and non-object lines before a match |
| Filters | Split at the first operator, allowing operators inside values; validate regex clauses eagerly | Equality/regex values and invalid patterns on empty input |
| Stats | Reject zero, negative and boolean integer bucket sizes | Parameterized invalid-input tests |
| Memory | Cursor line counting iterates instead of reading the entire file | Existing cursor tests; measured allocation comparison |
| Cleanup | Removed unreachable partial-line handling, redundant string casts/branches, unused private argument and stale speculative comments | Existing behavior tests retained |
| Typing | Correct generator annotations and warning-producing test expressions | Pyrefly reports zero visible diagnostics at warning severity |

23 regression cases were added, taking the suite from 226 to 249 tests. The new
bug tests were run against the old implementations first and failed as expected;
additional ownership and cursor coverage also passes. No test was skipped or
marked xfail to obtain green results. Existing intentional type ignores remain
(23 suppressed diagnostics reported by Pyrefly); no new ignores were added.

**Documentation corrections**

README, API reference and CLI reference now describe the full development extra,
persistent silent configuration after `capture_logs`, reliable serializer fallbacks,
transactional attachment failure, and truncation-safe IDs. CLI docs distinguish
`tail --once` metadata from live streaming; `errors --show-trace` returns trace IDs,
not traceback text; full percentile statistics require JSON. Source support and
stdin/MCP limitations are explicit. The shell comparison example is quoted to
avoid treating `>` as redirection. Plans remain historical design documents.

**Validation and behavior preservation**

The original baseline was 224 passed / 2 failed, Ruff clean, and Pyrefly with one
missing-import error plus 11 hidden warnings. Clean editable installs of `.[dev]`
were created at `/private/tmp/slogger-review-310` and
`/private/tmp/slogger-review-313`. Activate the relevant environment before checking;
Pyrefly discovers the interpreter through PATH.

```sh
source /private/tmp/slogger-review-313/bin/activate
python -m pytest -W error -q
python -m ruff check src tests examples
python -m pyrefly check --min-severity warn
```

Python 3.10 and 3.13 each pass all 249 tests, Ruff and warning-visible Pyrefly.
All 14 CLI command help paths pass. Six standalone examples run from a temporary
working directory with warnings treated as errors. Editable package import,
`py.typed`, and both schema resources were verified outside the checkout.
The optional FastAPI/uvicorn server was not launched. A shuffled test order
(seed 17) also passed the then-current 247-test suite. `git diff --check` is clean.

Normal-path APIs, schema keys, formatter conventions, compatibility aliases and
caller attribution remain covered by the existing suite. Behavior changes are
limited to the documented defect corrections above. Passing tests cannot prove
that every possible behavior is unchanged, especially for third-party handler
subclasses or timing-dependent workloads; the open findings are not covered by
new passing tests and are not claimed fixed.

**Optimization opportunities**

The implemented line-count change used approximately **22,588 bytes** peak traced
allocation versus **40,005,354 bytes** for the original `read()` implementation on
a 20 MB, 100,000-line file, with identical counts. This is a memory measurement,
not a general throughput claim; memory still scales with the longest single line.

Prioritize bounded span selection and persistent byte offsets for follow/watch:
current polling repeatedly counts and rereads prefixes of growing files. Replace
`_order_paths`' pairwise rotation checks with indexed base-name lookup for large
globs. Benchmark `@instrument` signature binding when `capture` is empty and the
emission gate on disabled log levels before changing their validation/configuration
semantics. Color policy and group-key normalization have duplicate implementations
that can be centralized later with parity tests. Avoid a broad abstraction or
processor pipeline solely to accomplish these cleanups.
