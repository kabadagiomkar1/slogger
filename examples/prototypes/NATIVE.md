# Native terminal prototype

This throwaway Textual application answers whether layout A, terminal input,
real-file paging, and reusable disk capture are feasible before production
implementation. It runs directly in a terminal; it has no HTTP server or web UI.
Primary source branch: `codex/tui-visual-prototype`.

## Run

From the repository root, one command installs script-only Textual dependencies
and uses the editable installed slogger package:

```sh
uv run --with-editable . examples/prototypes/native_tui.py
```

The already provisioned local environment can run it without installing again:

```sh
/tmp/slogger-tui-prototype-env/bin/python examples/prototypes/native_tui.py
```

No arguments creates 270 demo records across API, worker, and database sources.
The fixture includes Unicode, long rows, nested/literal field names, cross-file
traces, and missing/conflicting parent evidence. With actual JSONL files:

```sh
uv run --with-editable . examples/prototypes/native_tui.py api.jsonl worker.jsonl db.jsonl
```

Use explicit paths or shell-expanded globs; supplied order is concatenation
order. Malformed JSON/non-object records are skipped; physical line numbers
remain intact. This prototype accepts regular files, not stdin/live streams.

Optional flags: `--ram-mib 256`, `--disk-gb 10`, and
`--cache-dir /tmp/my-PROTOTYPE-cache`. The prototype defaults to a deliberately
small **32 MiB browsing-cache admission budget** for validation. The accepted
product RAM default remains provisional; neither number limits total RSS.
Platform scope of this artifact is macOS/Linux (POSIX file locking).

## Try

| Action | Key / interaction |
| --- | --- |
| Select and inspect | Up/down, click a row, PageUp/PageDown, Home/End |
| Pan long console rows | Left/right or terminal-reported horizontal wheel |
| Toggle JSON pane | `i` or JSON button; hidden initially below 100 columns |
| Resize JSON pane | `[` / `]` in five-percent steps |
| Filter | `f`, type an expression, Enter; Tab inserts the first suggestion |
| Search | `/`, type text, Enter; `n` / Shift+N navigate with wrap-around |
| Search scope/options | Full / Case / Word checkboxes |
| Tree | `t`; Space folds a span, Shift+Space folds/unfolds all |
| Reveal a tree search match | `n` unfolds its ancestors |
| Wrapping experiment | `w` toggles a fixed three-line console preview |
| Pin inspector / copy | `p` / `c`; full JSON copying requires terminal clipboard support |
| Refresh / cancel | Ctrl+R / Esc; previous successful view survives failed work |
| Settings | `,`; theme, save presentation defaults, clear unused captures |
| Quit | `q` while outside an input |

Filter examples use the actual Python IXR backend in bounded batches:

```text
level = "ERROR" and duration_ms >= 300
request.method = "POST" and ["http status"] >= 500
tags contains_all ["checkout", "retry"]
message contains "timeout" or logger_prefix("shop.db")
exists(trace_id) and not missing(span_id)
```

The prototype parser also supports typed comparisons, JSON literals, `in`,
`not in`, `contains_any`, `matches`, parentheses, and NOT/AND/OR precedence.
Origins returned for each IXR batch are mapped back to captured record IDs;
application fields are never used to store source identity.

## Storage and measured evidence

Captured bytes and record offsets live on disk; only viewport records are
decoded for browsing. Search/filter result positions are SQLite tables.
Each source has a fixed opening byte boundary. SHA-256 verification precedes
automatic reuse, including reuse of an unchanged dataset on explicit refresh.
Failed refresh retains the previous complete dataset. In-use datasets are
protected by file locks; seven-day inactivity expiry and a configurable disk
budget remove unused entries. Original input files are not modified.

The default cache is `/tmp/slogger-tui-PROTOTYPE-cache`. It intentionally survives
application exit to test reuse; OS temporary-directory cleanup can remove it.
Settings saved through the modal use `PROTOTYPE-settings.json` in that directory.
Query/search/navigation histories do not persist.

See [the measurement report](native-measurements.md) for timings, memory, and
validation evidence. These are local synthetic measurements, not production
latency guarantees or proof of performance over SSH.

## Deliberate limits

- Tree reconstruction is a representative preview of the first **10,000
  matching records**, with bounded ancestor enrichment. It preserves first
  appearance, demonstrates missing/conflicting parents, and keeps untraced
  records accessible. Lifecycle completion and duration inference are deferred.
- Autocomplete samples the first 5,000 physical lines per source, capped at
  512 field paths and 64 short scalar values per field. It is visibly described
  as sampled; complete rare-value discovery remains production work.
- Console rendering caps a row at 4,000 characters. Wrapping is a three-line
  preview, rather than full variable-height wrapping. Inspector preview caps
  at 64,000 characters. Search and copy examine the full accepted record.
- A single physical record above **8 MiB** is skipped in this experiment.
  Query batches are capped at 2,048 records / approximately 2 MiB source bytes,
  except a single larger accepted record. RAM admission weights are estimates.
- Full aggregate controls and span lifecycle semantics remain in the agreed
  design; they are outside this focused native feasibility step.
- Refresh preserves filter/search options, but resets pins and the tree preview;
  selection restoration currently requires the same captured position and
  verified content. Production needs stronger identity restoration and an
  atomic transition that also reapplies the active query before publishing.
- Budget checks stop growing capture/query work, but SQLite free pages and
  temporary index construction require a more complete production cache manager.
  A 5 GB captured dataset plus a full replacement can exceed a 10 GB budget.
- Headless/PTY checks cannot validate a real emulator's trackpad, mouse reporting,
  clipboard policy, or network latency. Manual local/SSH/tmux checks remain open.

This artifact is outside `src`; it adds no public entrypoint, mandatory runtime
dependency, logging behavior, or production storage contract. See
[the native prototype issue](../../.scratch/tui-consumers/issues/02-native-prototype.md)
and [confirmed design](../../.scratch/tui-consumers/design-interview.md).
