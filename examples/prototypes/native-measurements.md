# Native prototype measurements

Measured locally on 2026-10-04, macOS ARM64, Python 3.13.9, Textual 8.2.8.
[Raw measurements and source hashes](native-measurements.json) preserve evidence
for this throwaway artifact. These are single runs, not statistical benchmarks.

## Capture and reuse

Generated 1,024-byte JSONL objects in approximately 200 MB files: five files for
1 GB / 976,560 records, and 25 files for 5 GB / 4,882,800 records. Objects contain
varying IDs, levels, numeric/custom/nested fields, and padded custom payloads.

| Source total | First capture | First committed rows eligible for display | Verified reuse | Captured bytes + index |
| --- | --- | --- | --- | --- |
| 1 GB | 7.05 s | 0.045 s | 0.36 s | 1.050 GB |
| 5 GB | 34.33 s | 0.046 s | 2.01 s | 5.262 GB |

"First capture" means no reusable dataset. The OS file cache was warm from
fixture creation; physical cold disk I/O was not measured. Capture timings
exclude application startup. First committed rows are a storage milestone,
not measured input-to-screen latency. Reuse reads and hashes all source bytes.
Storage-only runs peaked around 52–57 MiB RSS. Raw JSON reports cumulative
managed cache size; the table derives per-dataset size from the increment.

## Native application paging

Headless Textual at 140×40, verified reopening, 200 noncontiguous record jumps,
and a jump to the final record. Each selection updates both console and JSON.

| Input | Warm app opening | Selection + headless redraw median / maximum | Peak app RSS |
| --- | --- | --- | --- |
| 1 GB | 0.47 s | 7.95 / 19.31 ms | 75.0 MiB |
| 5 GB | 2.15 s | 7.69 / 17.79 ms | 69.6 MiB |

The 32 MiB admission budget stabilized at 3,855 cached records in both runs,
with approximately 32 MiB estimated admission weight. It is an admission
estimate, not actual decoded allocation or total process memory. Timings include
Pilot/event-loop overhead and headless painting; they do not measure a physical
terminal, network, or keyboard device. RSS variance between runs is not a claim
that larger input uses less memory.

A complete 1 GB filter, `level = "ERROR" and duration_ms >= 300`, using public
IXR execution in bounded batches, took **8.03 s** and returned **34,173 records**.
Searching those filtered records for `timeout` took **0.33 s** and found all
34,173. Navigation during a background filter, cancellation, invalid-query
retention, and unchanged-refresh reuse were exercised separately.

## Correctness and native input observations

- Installed-package smoke runs on Python **3.10.20 and 3.13.9** exercised
  capture, filtering, search, tree folding/reveal, and JSON synchronization.
- Headless checks at **80×24 and 140×40** covered row clicks, keyboard selection,
  inspector toggling, horizontal navigation, wrapping, settings, and field/
  operator completion. Narrow layout hides the inspector automatically.
- A real pseudo-terminal emitted alternate-screen sequences, accepted arrows,
  SGR mouse input and a typed filter, and exited cleanly. This establishes
  protocol handling; it does not establish an emulator's mouse reporting.
- Changing contents while preserving file size and modification time prevented
  reuse. The previous capture remained unchanged; a new capture read new values.
- Blank lines, malformed JSON, and non-object JSON preserved correct skip counts
  and physical source-line attribution. Nested and literal-key filters and
  console/full-record search scopes were exercised.
- Reordering the 5 GB source set while its capture was open required another
  dataset. The 10 GB budget rejected replacement before copying and retained
  the active dataset. The same principle applies to a sufficiently changed 5 GB
  dataset: both versions plus indexes cannot necessarily fit simultaneously.
- `uv run --offline --with-editable . examples/prototypes/native_tui.py
  --capture-benchmark` verified the documented script launcher with cached deps.

## Remaining validation

Actual local-terminal and SSH/tmux mouse, trackpad, clipboard, latency, and CPU
behavior remain unverified. Computer-use access to macOS Terminal was denied;
headless/PTY evidence is reported separately. No remote host/session was supplied.

The fixture is regular synthetic JSON; it does not establish performance for
very large individual records, deeply nested objects, unusual Unicode, or every
trace topology. Full rare-value autocomplete and lifecycle reconstruction are
not implemented. The viewport renders only visible rows, but the entire future
product's working memory and SQLite temporary-storage accounting still need
production design and measurements. See [prototype limits](NATIVE.md).

## Reproduce

Generate disposable input outside the repository:

```sh
python3 examples/prototypes/native_benchmark.py /tmp/ixr-PROTOTYPE-fixtures --gb 5
```

Capture measurements (use a fresh cache for first capture; repeat for reuse):

```sh
uv run --with-editable . examples/prototypes/native_tui.py --capture-benchmark \
  --cache-dir /tmp/ixr-PROTOTYPE-measure-cache /tmp/ixr-PROTOTYPE-fixtures/source-*.jsonl
```

The generator writes about 5 GB; captured storage needs another approximately
5.3 GB. Disposable generated measurement files from this session are cleaned
after evidence is saved. The small demo and runnable environments remain.

Native-rendered headless screenshots: [console](native-console.png),
[filtered tree](native-tree.png), [80-column layout](native-narrow.png).
