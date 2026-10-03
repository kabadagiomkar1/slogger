# IXR execution benchmarks

Run from an editable install with `tools-polars` enabled:

```sh
python benchmarks/ixr_query_engine.py --small 200 --large 100000 --repeats 3 --output benchmarks/results/local.json
```

The [recorded run](results/ixr-2026-10-03.json) covers all sixteen cases: 200 and
100,000 rows, homogeneous and sparse records, selective and broad filters,
global descending sort followed by limit 50, and group-by with count/sum/mean.
Both adapters produced matching normalized output digests. The run used Python
3.13.9, Polars 1.44.2 and macOS arm64; exact platform and baseline Git revision
are in the JSON. No performance threshold is asserted in tests.

Datasets are deterministic JSONL with 32 logger groups and durations cycling over
0–999. Sparse records include missing/null nested duration fields and heterogeneous
scalar context values. Selective duration filtering accepts about 1% of the
homogeneous large source; broad filtering accepts about 90%. Sparse broad filtering
also includes missing context. All input is valid JSON; malformed-file overhead,
regex/array operations, concurrency and many-group stress are outside this matrix.

Each adapter/case runs in its own fresh subprocess. Dataset creation is excluded.
`cold_execute_ms` includes public `QueryPlan.execute()` ingestion, validation,
optional import, binding, execution and output construction. The builder has a
separate timing. Three further executions reuse the same logical plan but reparse
and rebind the source: there is no persistent dataframe cache. Filesystem cache is
uncontrolled, so “cold” means process/adapter cold, not uncached disk access.

Peak RSS is the worker process high-water mark, including interpreter, libraries,
input and output. The cold snapshot precedes digesting and diagnostic probes;
the repeated-worker peak is captured after repeated runs. It is not an allocation
counter or a subtraction of baseline RSS. macOS bytes and other `resource` platform
KiB are normalized to bytes. Results retain prior process initialization overhead.

Independent stage probes report Reader ingestion (JSON parsing plus identity and
accounting), row wrapping, warm validation/preparation, conversion, expression
lowering, native collect and reconstruction. Filtering probes use actual bounded
batches. For global sorting/grouping, conversion is measured independently and the
actual global helper is timed inclusively; native-only execution/reconstruction
are `null` because those internals do not expose reliable independent seams.
Python reports inclusive prepared-engine execution and result packaging. These
probes operate on already parsed rows, rerun work and differ from the public path;
**do not add them to reconstruct end-to-end time**. This avoids misleading attribution
of generator/lazy execution to the wrong stage. No public API was added for timing.

Selected 100,000-row observations (milliseconds and MiB, rounded):

| Shape / workload | Python cold | Polars cold | Python repeated median | Polars repeated median | Python cold RSS | Polars cold RSS |
|---|---:|---:|---:|---:|---:|---:|
| Homogeneous selective | 206.5 | 271.5 | 204.8 | 211.1 | 37.3 | 77.7 |
| Homogeneous broad | 277.4 | 340.7 | 271.9 | 282.7 | 112.7 | 153.3 |
| Homogeneous sort | 303.3 | 364.0 | 305.0 | 319.5 | 221.2 | 274.5 |
| Homogeneous group | 305.6 | 357.4 | 304.1 | 320.8 | 55.3 | 275.8 |
| Sparse broad | 277.4 | 326.6 | 274.8 | 270.8 | 83.6 | 124.6 |
| Sparse group | 310.2 | 350.8 | 303.7 | 304.7 | 55.2 | 261.7 |

At 200 rows, cold Python execution took 2.3–3.6 ms and cold Polars execution
52.4–126.3 ms; repeated medians were roughly 0.5–0.8 and 0.8–1.2 ms respectively.
The optional import dominates small cold queries. On this run native execution did
not provide a consistent end-to-end advantage; sparse broad repeated filtering was
slightly faster in Polars, while other results were similar or slower. Python remains
the default. These observations are machine/workload specific, not general speedup
claims. Parsing and lossless lane conversion still occur in Python, and records are
reconstructed for callers. Global Polars operations materialize input, explaining
substantial memory costs even when a downstream limit or small group output exists.

Compatibility evidence: final review baseline 5e85e48 passed all 507 tests on
Python 3.10.20 with Polars 1.29.0 and Python 3.13.9 with Polars 1.44.2. This
benchmark refresh records that same committed revision, including compensated
reference floating reductions and checked exact native fixed-point lanes. An earlier fresh installation
without Polars verified logging/tools imports, Python filter/count aggregation and
CLI help. The final suite also verifies optional dependency absence in a fresh
interpreter, including explicit `dependency_missing` with its retained ImportError
cause. The optional
range is `polars>=1.29,<2`; this is a tested floor and broad declared range, not a
claim that every intermediate version or future release was exhaustively tested.
The benchmark digest rounds float values to eight decimals and normalizes temporary
source prefixes; exact typed behavior and tighter numeric parity are covered by the
behavioral suite rather than this digest.
