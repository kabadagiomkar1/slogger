# Native investigation opening

The optional native application opens supplied finite regular JSONL files into
one stable disk dataset, then presents a console stream and a narrower JSON
inspector. Install **this repository**; the PyPI name `slogger` belongs to an
unrelated package.

```sh
pip install -e ".[tools-tui]"
slogger-tui worker.jsonl api.jsonl worker.jsonl
# Equivalent module launcher:
python -m slogger.tools.tui worker.jsonl api.jsonl
```

Python 3.10–3.13 and Textual `>=8.2.8,<9` are the initial dependency range.
The storage allocation contract currently requires POSIX `statvfs`/`st_blocks`.
Installed headless and native interaction tests run on macOS with CPython 3.10
and 3.13, Textual 8.2.8; actual local emulator, Linux, SSH, and multiplexer
qualification remains in the terminal-validation slice. Core logging and Python
IXR do not require Textual, Rich, or Polars. A missing native dependency produces
an actionable `dependency_missing` diagnostic.

Opening currently completes capture before launching the screen. Input order
and repeated occurrences are preserved. Each file's opening byte boundary is
established before capture; later appends remain outside this dataset. Capture
checks descriptor/path identity and rereads the opening bytes to verify their
hashes. Observed truncation, replacement, or mutation fails capture; this is an
application boundary, not an operating-system snapshot for concurrent rewrites.

UTF-8, universal newlines (LF/CRLF/CR), blank-line handling, malformed JSON and
non-object skips follow shared source decoding. A valid final object without a
newline is admitted; a malformed final line is diagnosed and skipped. Physical
lines remain separate from displayed positions and repeated-input identities.
Original application fields are untouched, including `_id` and metadata-like keys.

Use Up/Down, PageUp/PageDown, Home/End, or a console click to select a record.
Tab switches panes; each pane has independent scrolling; Q quits. The console
recognizes timestamp, level, logger, message, and canonical `span` (with
`span_name` as fallback), hides known attribution/trace/exception metadata, and
shows custom fields. Logger columns may elide text to align message starts.
Generic objects are shown as JSON. The inspector retains the complete parsed
record and prettifies it with syntax colors; only visible console rows and JSON
lines are rendered. There is no fixed JSON character or line preview cap.
Wrapping, presentation controls, pins, field actions, and richer inspector
navigation are subsequent slices of the approved production specification.

## Headless operations

```python
from slogger.tools import Investigation, ResourceLimits

with Investigation.open(["worker.jsonl", "api.jsonl"], limits=ResourceLimits()) as session:
    if session.status.complete:
        session.require_ready("my complete-dataset operation")
    page = session.page(0, 100)
    # Application records, origins and dataset identities are aligned separately.
    print(page.records, page.origins, page.identities)
    next_page = session.page(page.next_offset, 100)
    diagnostics = session.diagnostic_page(0, 100)
    print(session.status, session.sources, session.resources, diagnostics)
```

`CaptureStatus` reports phase, record count, consumed opening bytes, total opening
bytes, and skipped lines. Capture errors return a `failed` session with retained
admitted records and structured diagnostics; complete-dataset operations must
call `require_ready`, which raises `dataset_incomplete` unless capture completed.
Storage setup failure raises `ToolError`; invalid limits raise `ValueError`.
`RecordPage.complete` describes dataset completeness. Pages can contain fewer
than requested records because of the memory budget; follow `next_offset` rather
than adding the requested page size. Origins retain original file/physical-line
locations. Identities separate dataset ID, ordinal, and input occurrence.
`diagnostics` is a disk-backed sequence, not an in-memory full-input list; iterate
it one diagnostic at a time or use bounded `diagnostic_page` delivery.

Close is idempotent and removes session-owned records, fixed-width offset indexes,
diagnostics, and browsing-cache contents. Use a context manager, including for
failed sessions. `storage_dir` selects the parent of a private temporary session
directory; completed capture reuse and persistent cache leases are subsequent
work. These local handles are not a CLI/MCP transport schema.

## Initial resource envelope

All values are configurable through `ResourceLimits`. Defaults are provisional,
not measured 1–5 GB capacity or total-process RSS guarantees:

| Resource | Initial default | Contract |
| --- | --- | --- |
| Managed disk | 10 GiB | Session records, indexes, diagnostics, directory allocation, and reserved output growth |
| Browsing RAM cache | 256 MiB | Encoded records plus conservative per-entry accounting; LRU eviction |
| Source line / admitted record input | 8 MiB | Physical UTF-8 bytes, including terminator; larger lines fail explicitly |
| Working admission | 64 MiB | Decoded object, prettified JSON/line storage, and four times raw bytes |
| Decoded page | 16 MiB | Recursive object size plus per-record delivery allowance |
| Records per page | 256 | Maximum requested delivery count, independent of dataset size |

Record admission measures recursive Python object size and the complete prettified
representation before publication. A record that cannot fit the declared working
or page envelope causes `record_too_large` and an explicit incomplete session;
it is never silently dropped or truncated. Parsing and rendering have temporary
allocations bounded by the admitted input/record envelope; these budgets do not
control Python allocator overhead, Textual's entire process, or OS buffers.
Callers retaining many returned pages own that additional memory.

The shared `ManagedStorage` creates named session files, reserves growth before
writing, accounts for the greater of file length and allocated blocks, and
checks actual allocation after writes. Disk exhaustion produces `resource_limit`;
failed capture preserves admitted records until close. Future indexes/results,
journals, staging, and spill jobs must use this mechanism. Cross-process total
cache accounting, expiry, reuse, and protected clearing belong to the cache
lifecycle slice. The default RAM candidate and practical scale envelope will be
revisited using production measurements.

Launcher flags expose `--storage-dir`, `--disk-budget-mib`, `--ram-cache-mib`, and
`--max-record-mib`. The headless API exposes all limits. Increasing the source
line limit alone does not override working/page admission.
