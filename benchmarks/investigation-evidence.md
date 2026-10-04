# Investigation qualification evidence

Status: complete 1 GB browsing comparison; full 1–5 GB operation matrix pending.
Ticket 24 remains claimed until the remaining acceptance evidence is complete.

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

See the [reproduction and cleanup instructions](README.md). The forthcoming
operation matrix will use the chosen 64 MiB configuration at its own exact clean
source pin; these explicit 64/128/256 measurements retain their original source
and effective configurations. No broader performance acceptance is inferred here.
