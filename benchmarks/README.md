# IXR execution benchmarks

Run from an editable install with `tools-polars` enabled:

```sh
python benchmarks/ixr_query_engine.py --small 200 --large 100000 --repeats 3 --output benchmarks/results/local.json
```

The version-2 harness measures the IXR-only implementation. It covers sixteen
cases: two sizes, homogeneous/sparse records, selective/broad filters, global
sort followed by limit 50, and grouping with count/sum/mean. Dataset generation is
deterministic JSONL with 32 logger groups and durations cycling over 0–999.
Application `_id` fields are ordinary data. Sparse inputs include missing/null
nested fields and heterogeneous scalar context. All lines are valid; malformed
input, regex/arrays, concurrency, and many-group stress are outside this matrix.

Each adapter/case runs in a fresh subprocess. Dataset generation is excluded.
`cold_execute_ms` includes public execution, parsing, origin handling, validation,
optional import, binding, native execution, reconstruction, and result packaging.
Builder time is separate. Repeated executions reuse the logical plan but reparse
and rebind files; there is no persistent dataframe cache. Filesystem cache is
uncontrolled: cold means process/adapter cold, not uncached disk access.

Peak RSS is the worker high-water mark, including interpreter, libraries, input,
and output. Cold/repeated snapshots precede digesting and independent probes.
It is not an allocation count or baseline subtraction. macOS bytes and other
`resource` platforms' KiB are normalized to bytes; unavailable RSS is null.

Independent diagnostic probes report source ingestion with origin/row creation,
warm validation/preparation, conversion, lowering, native collect, reconstruction,
and Python inclusive prepared execution plus record/origin packaging. Native
filter probes use actual bounded batches. Global sorting/grouping helpers are
timed inclusively; their native-only execution/reconstruction fields are null.
Probes use internal ownership modules, rerun work on parsed rows, and overlap
conceptually. **Do not sum probes to reconstruct public execution time.** No public
timing interface or speed threshold is introduced.

The correctness digest includes ordered application records and aligned origins;
file paths are reduced to basenames to remove temporary-directory variation.
Application `_id` values are never normalized. Floats are rounded to eight decimals
for this coarse cross-adapter check; exact typed semantics and `1e-12` numeric
parity belong to the behavioral suite. The harness also verifies file origins
against the generated record's original position and checks aggregate origins
are all absent. Git revision, Python/Polars versions, platform, and row counts
are recorded with each run. No general speedup is claimed.

## Integrated migration evidence

[The IXR-only run](results/ixr-only-2026-10-03.json) measured revision
`4b777b0001d6a15c4387ae0872fdc16b3610a651` on 2026-10-03: Python 3.13.9,
Polars 1.44.2, macOS arm64, 200 and 100,000 input records, three repeated
executions per case. All sixteen ordered record/origin digests matched across
adapters; source-position and aggregate-origin assertions passed.

The table reports repeated-execution medians and worker peak RSS after repeated
execution, before independent probes. Python had a lower median and smaller RSS
in every case in this matrix. These measurements do not predict other workloads,
platforms, or native-only execution; parsing and reconstruction are included.
Origin storage is included, but no origin-free comparison isolates its cost.

| Size / shape / query | Python median ms | Polars median ms | Python / Polars peak MiB |
| --- | ---: | ---: | ---: |
| small / homogeneous / selective_filter | 0.50 | 0.97 | 33.5 / 71.3 |
| small / homogeneous / broad_filter | 0.63 | 0.95 | 33.8 / 71.1 |
| small / homogeneous / sort_top50 | 0.54 | 0.96 | 34.0 / 72.0 |
| small / homogeneous / group | 0.74 | 1.20 | 33.6 / 76.0 |
| small / sparse / selective_filter | 0.53 | 0.81 | 33.6 / 71.6 |
| small / sparse / broad_filter | 0.60 | 1.05 | 33.8 / 72.1 |
| small / sparse / sort_top50 | 0.54 | 0.90 | 33.9 / 71.9 |
| small / sparse / group | 0.73 | 1.05 | 33.6 / 76.0 |
| large / homogeneous / selective_filter | 203.63 | 219.86 | 34.5 / 76.2 |
| large / homogeneous / broad_filter | 291.14 | 314.62 | 114.0 / 155.2 |
| large / homogeneous / sort_top50 | 315.77 | 369.30 | 226.5 / 285.1 |
| large / homogeneous / group | 304.45 | 312.08 | 52.8 / 291.3 |
| large / sparse / selective_filter | 209.96 | 230.41 | 34.0 / 76.2 |
| large / sparse / broad_filter | 280.74 | 318.09 | 83.5 / 125.2 |
| large / sparse / sort_top50 | 310.83 | 321.79 | 212.2 / 270.7 |
| large / sparse / group | 300.91 | 312.23 | 52.8 / 278.5 |

## Historical evidence

[The pre-migration run](results/ixr-2026-10-03.json) measured revision `5e85e48`
using the old Reader, synthetic identity, and predicate facade. Its version-1
stage names and digests differ from this harness. It is retained as historical
raw evidence, **not a measurement of the IXR-only implementation**. The integrated run above uses a different harness contract; these runs are not
a controlled before/after performance comparison.

The declared optional range is `polars>=1.29,<2`; endpoint testing does not imply
all intermediate or future versions have been tested. Core logging and Python
execution require no dataframe dependency.
