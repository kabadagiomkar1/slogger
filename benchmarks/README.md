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
| Homogeneous selective | 202.4 | 257.3 | 198.6 | 203.7 | 37.2 | 77.9 |
| Homogeneous broad | 270.8 | 319.8 | 267.4 | 271.4 | 112.8 | 153.0 |
| Homogeneous sort | 299.1 | 353.3 | 310.7 | 310.8 | 221.2 | 274.8 |
| Homogeneous group | 299.0 | 344.1 | 287.7 | 308.8 | 55.3 | 273.5 |
| Sparse broad | 282.5 | 318.4 | 278.5 | 270.1 | 83.6 | 124.4 |
| Sparse group | 301.2 | 341.3 | 293.8 | 295.3 | 55.3 | 259.0 |

At 200 rows, cold Python execution took 2.2–4.4 ms and cold Polars execution
51.0–110.2 ms; repeated medians were roughly 0.5–0.7 and 0.8–1.0 ms respectively.
The optional import dominates small cold queries. On this run native execution did
not provide a consistent end-to-end advantage; sparse broad repeated filtering was
slightly faster in Polars, while other results were similar or slower. Python remains
the default. These observations are machine/workload specific, not general speedup
claims. Parsing and lossless lane conversion still occur in Python, and records are
reconstructed for callers. Global Polars operations materialize input, explaining
substantial memory costs even when a downstream limit or small group output exists.

Compatibility evidence: baseline 9045e18 passed all 496 tests on Python 3.10.20
with Polars 1.29.0 and Python 3.13.9 with Polars 1.44.2. A fresh installation without
Polars verified logging/tools imports, Python filter and count aggregation, explicit
`dependency_missing` with the retained ImportError cause, and CLI help. The optional
range is `polars>=1.29,<2`; this is a tested floor and broad declared range, not a
claim that every intermediate version or future release was exhaustively tested.
The benchmark digest rounds float values to eight decimals and normalizes temporary
source prefixes; exact typed behavior and tighter numeric parity are covered by the
behavioral suite rather than this digest.
