# Native investigation qualification

Run these repository modules from an installed checkout with the development
requirements and optional Textual dependencies already available. Input creation
requires an explicit external task-owned directory. No import creates files.

```sh
python -m benchmarks.investigation_fixtures --root /tmp/slogger-fixtures --self-test --generate
python -m benchmarks.investigation_qualification --measure --manifest /tmp/slogger-fixtures/manifest.json --dataset 1GB --run-dir /tmp/slogger-run-1gb --checkout /absolute/checkout --expected-revision FULL_COMMIT --native
```

The streaming generator creates forty roughly125MB ASCII JSONL sources. The
first eight also supply the1GB case, without duplicate input storage. It records
exact content hashes, physical counts, numeric presence/null/sum expectations,
all64 typed groups and cross-file canonical trace/lifecycle populations. Small
formula/repeated-content verification precedes full generation. `--smoke` creates
a624-record complete fixture with its own manifest; it establishes harness
correctness, not scale acceptance. All paths and manifests remain task-owned.

Measurements require a clean exact revision and the installed package pointing
at that checkout. Use a fresh run directory. Default managed disk admission is
10GiB and the fresh encoded browsing-cache default is64MiB; any different configured disk budget requires `--characterization NAME` and
separate evidence. First observed browsing, capture/index completion, verified
reuse, job execution and every result page's independent oracle verification
have distinct phases. Complete operations never use previews, group caps or
sampled population substitutes. Result/group/value paging retains bounded state.

The process-subtree sampler includes child workers and records allocated managed
files, public reservations/catalog headroom and statuses. Phase CPU includes
profiling and, in verification phases, the oracle; repeated `ps` subprocess CPU
also appears in waited-child usage. Sampled simultaneous RSS/disk peaks are lower
bounds. Configured browsing-cache bytes are distinct from process RSS and
operation/record admission. OS caches are uncontrolled; generated inputs and
source hashing warm them. An empty application cache is never called cold storage.
Optional `--machine-preparation PATH` attaches separately collected machine facts;
runtime platform, Python/dependency versions and logical CPU count are recorded.

`--controls` runs exact8MiB±1 encoded probes, decoded array shapes and controlled
combined refresh refusals. It requires the same pinned checkout arguments.
Add `--native` to verify each complete candidate in the actual native JSON inspector,
including the complete pretty document, console/JSON horizontal panning, wrapping
and wrapped-line movement, movement into/out of the record and explicit
prefix browsing when capture refuses it. No renderer cap or preview is introduced.
Capture and individual operation envelopes can differ; reports preserve every
explicit refusal and verify the original owner/view remains usable. Headless
Textual idle/navigation evidence is separate from actual terminal/SSH validation.

`--measure --browsing-only` runs complete forward cache priming and a deterministic
reverse revisit, independently of the complete operation matrix. Run the1GB case
in separate processes/run directories at `--ram-mib 64`, `128` and `256`; each run
starts an empty application capture cache and verifies reuse before browsing.
Page-call totals/maxima and bounded logarithmic latency buckets exclude subsequent
oracle checks; phase CPU/RSS include those checks and profiling. Every record and
origin is verified in both passes; the pattern has no sampled population substitute.

Keep complete inputs until durable concise measurements, source hashes and code
identity are recorded. Closing a durable capture can intentionally retain its
cache entry; a close-settled event does not mean cache allocation is zero. Clear
only unlocked entries in the task-owned cache and remove task-owned aliases/input
files after final evidence is saved. Never clear user caches or change OS caches.

See [recorded qualification evidence](investigation-evidence.md) for the completed
1 GB RAM comparison, complete 1 GB operation/native matrix and intentionally
partial 5 GB run, with their exact source/input/machine/cache conditions. Further
exhaustive qualification is deferred at the user's direction; current expensive
autocomplete discovery remains a limitation. A different TUI suggestion policy
is proposed but not implemented. Preparation, tiny checks and partial runs do
not establish complete 5 GB qualification or an RSS/latency guarantee.
