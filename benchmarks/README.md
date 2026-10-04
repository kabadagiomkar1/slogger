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
10GiB; any different configured budget requires `--characterization NAME` and
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
Capture and individual operation envelopes can differ; reports preserve every
explicit refusal and verify the original owner/view remains usable. Headless
Textual idle/navigation evidence is separate from actual terminal/SSH validation.

Keep complete inputs until durable concise measurements, source hashes and code
identity are recorded. Closing a durable capture can intentionally retain its
cache entry; a close-settled event does not mean cache allocation is zero. Clear
only unlocked entries in the task-owned cache and remove task-owned aliases/input
files after final evidence is saved. Never clear user caches or change OS caches.

Current scale results belong to ticket24; preparation and tiny checks alone do
not establish1/5GB qualification or an RSS/latency guarantee.
