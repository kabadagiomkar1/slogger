# Investigation qualification evidence

Status: complete 1 GB operation/native matrix; partial 5 GB matrix. Further
exhaustive benchmarks are deferred at the user's direction so the committed core
can be used first. Ticket 24 remains claimed, and actual terminal/SSH validation
in ticket 23 remains pending.

Subsequent qualification runs use a five-minute measured-phase deadline by default
(`--phase-timeout 300`). A deadline aborts the run with a nonzero exit, records the
failed phase, releases owned sessions/jobs through existing cleanup, and retains
`events.jsonl` and earlier measurements. Nested phases cannot extend their outer
deadline. Cleanup itself is outside the measurement deadline; this is a phase
limit, not a process-kill timer. POSIX timers run on the runner's main thread.
Use a larger explicit limit for deliberate characterization, or
`--phase-timeout 0` to disable it. These runner changes do not alter the historical
measurements below or resume the deferred exhaustive matrix.

Run the native interaction profile in the [development workflow](../docs/agents/development.md)
before performance work, then start with the generator's `smoke` dataset. Preserve
the exact command and revision alongside partial evidence and inspect failed phase
events before expanding to 1 GB or 5 GB. A deadline is an unfinished measurement,
not a successful performance result.

The historical measurements used the committed implementation at
`364acb9f6266204961a57d1414b9e5bbe8030fce`, tracked tree
`a109ce56728e588ccfde222514d1273d6b29c244`. It is exactly the reviewed `d33efd7`
code. Those results describe that measured revision. The current runner adds
phase deadlines; it has not requalified subsequent changes at full scale.
The user requested considering bounded progressive or on-demand TUI suggestions.
That policy remains a proposal and has not changed delivered autocomplete behavior
or exact Investigation filter/search/tree/aggregate semantics.

## Complete 1 GB and interrupted 5 GB measurements

Both runs used fresh application capture caches, actual 64 MiB encoded browsing
cache, normal 10 GiB managed disk, 8 MiB encoded record, 64 MiB operation working
memory and 16 MiB decoded page limits. Input was 845,760 records / 999,368,579 bytes
for 1 GB and 4,222,864 records / 4,996,812,998 bytes for 5 GB. All sources were
whole-record ASCII files of approximately 125 MB, with sparse/custom/nested and
literal dotted fields, long messages, cross-file lifecycle evidence and unique
request values. The [fixture identity](evidence/fixture-identity.json) retains all
40 file hashes, sizes/counts, generation seed and independent numeric/group
expectations. The first eight files supply 1 GB without duplicate source storage.

| Phase | Complete 1 GB seconds | Partial 5 GB seconds |
| --- | ---: | ---: |
| First observed headless browse | 0.0708 | 0.0766 |
| Complete capture | 42.371 | 208.459 |
| Every record, identity and origin verification | 14.369 | 72.554 |
| Verified durable reuse | 0.984 | 4.977 |
| Complete field/value discovery construction | 1,346.213 | 8,012.276 |
| Every discovery value/field verification | 5.802 | 29.236 |
| cost_units numeric summary | 244.253 | 1,085.526 |
| latency_ms numeric summary | 284.021 | 1,283.792 |
| All 64 typed numeric groups | 307.527 | 2,547.931 |
| All unique request groups | 426.812 | interrupted; not verified |
| Complete trace tree | 229.763 | not run |
| Applied scope and ancestor context tree | 245.938 | not run |
| Complete native discovery settlement | 1,530.958 | not run |
| Native settled idle observation | 5.008 | not run |
| Native navigation with filter worker | 8.995 | not run |
| Refresh replacement capture | 44.656 | not run |
| Staged latest explicit filter | 4.390 | not run |
| Every staged filter membership verification | 2.818 | not run |
| Atomic owner transfer | 0.0678 | not run |

Complete discovery is the field/value index used by autocomplete, not compilation,
capture, first browsing or total UI startup. Its observed 1 GB/5 GB construction
cost was about 22/134 minutes; the native 1 GB repeat took about 26 minutes.
These complete autocomplete costs are a current usability limitation. Exact
correctness and bounded memory do not establish acceptable autocomplete latency.
The first observed browse times above measure the public headless record page.

The complete 1 GB run exited 0 with no failed operations, refusal or sampler error.
All five filter populations and full/console plus four applied-scope searches
matched independent formulas. Discovery verified 60 fields, every one of 845,760
request values, 52,861 trace values, every span ID/label and eight late keys.
Both numeric summaries and all 64 typed groups matched every metric. All 676,608
selected-presence request groups were checked through bounded pages. Full tree
verification retained every record, 52,861 traces and 158,589 spans; the scoped
tree checked 31,677 matching leaves and 26,739 ancestor-context nodes. Filter and
refresh cancellations retained the successful owner. Headless native navigation
covered 32 keys, including while a filter worker ran. Successful refresh verified
all staged membership and transferred atomically to 845,761 records while the
previous owner remained usable during staging.

The 5 GB run passed complete capture/record-origin/reuse, all five filter and six
search population oracles, full discovery, both numeric summaries and all 64
typed groups. Discovery checked all 92 fields, 4,222,864 request values, 263,930
trace values, every span ID/label and 40 late keys. The user then explicitly stopped
further exhaustive work. SIGINT to the owned runner settled exit 130 during unique
request grouping after 94.731 seconds; its last sample had examined 556,292 records
and built 445,032 partial groups. Those partial counts are not a complete result
or correctness substitute. No high-cardinality oracle, 5 GB trees, matrix-specific
cancellation checks, native run or refresh ran. No full 5 GB pass, normal-budget
refresh outcome or higher-budget characterization is claimed.

| Sampled resource evidence | Complete 1 GB | Partial 5 GB |
| --- | ---: | ---: |
| Concurrent process-group RSS lower-bound peak, bytes | 170,950,656 | 203,292,672 |
| Allocated managed disk lower-bound peak, bytes | 2,925,342,720 | 9,397,579,776 |
| Simultaneous allocation + reservation + catalog reserve peak, bytes | 2,925,442,048 | 9,657,258,688 |
| Retained allocation after close, bytes | 2,069,135,360 | 5,150,740,480 |

The 1 GB final public resources reported zero reservation. After the 5 GB
interruption, the closed catalog independently reported zero reservation and its
capture lease accepted a nonblocking exclusive lock. Transient query allocation
was removed; completed durable captures remain accounted for reuse. Close is
not cache reclamation. Original inputs, aliases, raw events and caches are retained;
no task or user sources were deleted. Separate allocation/reservation maxima are
not added together to invent an overlap peak.

The [complete 1 GB evidence](evidence/matrix-1gb-364acb9.json) and
[explicit partial 5 GB evidence](evidence/matrix-5gb-364acb9-partial.json) preserve
bounded phase/status/CPU/resource/oracle summaries, native events where executed,
exact measured code/harness/runtime/input identities and raw-event hashes. They do
not retain populations of result rows or groups. Raw task paths identify historical
artifacts; the maintained generator, oracles and identities enable reproduction.

## Admitted-record and controlled refusal evidence

[Nine admission controls](evidence/admission-controls-364acb9.json) passed their
assertions at the same measured source and limits. Encoded 8 MiB minus one and
exact 8 MiB records passed complete filter/search/numeric/discovery/tree operations
and full native inspection, pan, wrap and line navigation. Encoded 8 MiB plus one
was refused with an actionable diagnostic and usable captured prefix. A dense
150,000-element record passed all five operations and native checks. Dense
200,000/300,000-element records were capturable and fully inspectable but tree
working admission refused them honestly; the previous owner stayed usable. A
one-million-element record was refused by decoded capture admission despite its
encoded size fitting the source limit. Combined original/replacement disk refusal
controls preserved usable prior owners in temporary and durable modes; reservations
settled and temporary allocations were removed. Raw bytes, decoded residency and
per-operation admission are distinct envelopes, not interchangeable limits.

The near-limit native control RSS lower-bound peak was 395,100,160 bytes, including
candidate generation and complete body verification. No renderer preview or body
cap was used. Full record layout still has linear costs; this evidence describes
tested shapes, not a universal record-size or presentation-speed guarantee.

All current matrix/control runs used installed Python 3.13.9, Textual 8.2.8,
Rich 15.0.0 and Polars 1.44.2 on Apple M4 / 10 logical CPUs / 16 GiB RAM,
macOS 26.6.2 arm64. Phase CPU includes verification/profiling, sampler and repeated
ps children; waited-child CPU must not be attributed solely to query workers.
Sampled simultaneous peaks are lower bounds. OS caches/activity were uncontrolled
and generated/source-hash warmed. No OS caches were changed. Agent checks did not
compete during measurement; concurrent user demo use was authorized but not
observed or treated as machine-wide quietness. Native evidence is Textual headless;
actual terminal gestures, clipboard and SSH validation remain pending in ticket 23.

Core checks retain their exact pins: both Python endpoints passed 558 tests at
`7ff6a6c`; later relevant native/default/discovery suites passed at their own
revisions, including 87 tests per endpoint at `d33efd7` and exact source-equivalent
integration `364acb9`. No new exact-tip full-suite or web-UI CPU comparison is claimed.
Further exhaustive runs are deferred; the proposed suggestion policy has not been
implemented. See [reproduction and cleanup instructions](README.md).

## Complete RAM-default comparison

The fresh encoded browsing-cache default is **64 MiB**. Three separate processes
captured and verified every record, opened the verified durable capture, then
browsed the complete population forward and in deterministic reverse page order.
Each pass verified all 845,760 records, original identities and physical origins
across 3,304 page calls. All three runs completed without refusal or oracle failure.
Explicit saved preferences and CLI/API overrides retain their selected values.

| Cache MiB | First observed browse s | Complete capture s | Verified reuse s | Forward / reverse page-call totals s | Sampled peak process RSS MiB |
| --- | --- | --- | --- | --- | --- |
| 64 | 0.0731 | 42.142 | 0.821 | 13.903 / 13.950 | 132.19 |
| 128 | 0.0684 | 42.103 | 0.936 | 13.867 / 13.904 | 218.75 |
| 256 | 0.0692 | 42.514 | 0.900 | 14.102 / 13.945 | 394.52 |

64 MiB is the lowest tested practical candidate. Larger caches provided similar
observed page-call totals while sampled RSS increased. This is one representative
complete browsing pattern, on one machine, in fixed 64/128/256 order. It does not
establish a latency guarantee, cold-storage result, total RSS limit, or the separate
complete query/refresh operation matrix. Record, page, operation and native widget
allocations remain separate from the encoded cache budget.

The measured checkout was `f902d742bc9d8691c1e44cc15efb61b06df80064`, with tracked
tree `1abfbebc7f19197ec822f0710186876ff969aa7e`, exactly equal to the focused-tested
rendering commit `bcfdd3a51113c295ad1b03fd2288b071bcfb30ab`. Python 3.13.9 used the
installed editable checkout; machine Apple M4, 10 logical CPUs, 16 GiB RAM,
macOS 26.6.2 arm64. Normal limits were 10 GiB managed disk, 8 MiB source line,
64 MiB operation working memory, 16 MiB decoded page and 256 page records. Only
encoded cache admission varied. No system caches were changed; generated input,
source hashing and prior phases warm uncontrolled OS caches. An empty application
cache is not called cold storage.

Input was 999,368,579 bytes in the first eight whole-record files of the reusable
40-file deterministic ASCII fixture, seed 20261004. Ordered input identity is
`7e0eaf62518b1cdeba9a35365c3b6bdea0172a9e702bc9e54e39b86c5b47e12c`.
Original manifest SHA256 is
`bcb91eb3e0562f9feffdbc6e2d443378f44462ab0c7088447fc6cb6e7ab7e4cc`;
measured runner SHA256 is
`5949f513e0ad42a320c39fb8e705484b7f5d4a001202ad879eea90d8808bf839`.
The [compact fixture identity](evidence/fixture-identity.json) retains exact sizes,
hashes, counts, distributions and full dataset numeric/group expectations, omitting
only repeated per-file grouped numeric tables. Its absolute source paths
identify historical task-owned files. Regenerate sources in an explicit owned
location using the maintained generator and use its fresh path-bearing manifest.
Content/ordered identities supply the reproducible comparison.

[Bounded RAM evidence](evidence/ram-1gb-f902d74.json) retains every phase's CPU,
resources, status, sampled peaks, page histogram and input/runtime identity. Page
call times exclude following oracle checks; phase CPU/RSS includes verification
and profiling. Waited-child CPU includes repeated `ps` subprocesses and must not
be attributed solely to query workers. Sampled peaks are lower bounds. Reservations
settled to zero, while closing intentionally retained about 1.034 GB of durable
capture allocation per run; this is not cache reclamation. Complete inputs and
these task-owned caches remain available for later measurement and cleanup.


## Original interrupted diagnostic matrix

The first selected-default operation matrix at `14b14f5` is explicitly partial.
It completely captured and independently verified all 845,760 records and origins,
verified durable reuse, and passed the complete filter/search population oracles.
Full discovery construction finished in 2,134.394 seconds with no diagnostics,
1,363.108 seconds self CPU, 161,775,616-byte sampled phase RSS peak and
1,907,281,920-byte managed allocation; reservations settled to zero. Its complete
value verification was interrupted after 119.969 seconds (112.805 seconds self
CPU) inside prefix lookup. The read-only query plan showed a field/source scan
without a spelling range. No full discovery oracle or complete matrix pass is
claimed. Instrumentation/verification CPU and uncontrolled-cache caveats above
apply; timings are observations, not guarantees.

[Bounded original partial evidence](evidence/matrix-1gb-14b14f5-partial.json)
retains exact source/input/runtime/runner identity, phase outcomes and resources,
interruption reason, query-plan metadata and cleanup. Transient index deletion
settled; close retained 1,034,543,104 bytes of durable capture, not zero allocation.
A focused real public-path profile confirmed repeated field/value writes and
catalog publication. Bounded occurrence windows and indexed prefix reads were
implemented and checked on both Python endpoints before the complete 1 GB
replay at `364acb9`. That later pass does not retrospectively qualify this
original interrupted run.
