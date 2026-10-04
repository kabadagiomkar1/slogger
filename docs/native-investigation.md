# Native investigation opening

The optional native application opens supplied finite regular JSONL files into
one stable disk dataset, with progressive console browsing and a narrower JSON
inspector during capture. Install **this repository**; the PyPI name `slogger` belongs to an
unrelated package.

```sh
pip install -e ".[tools-tui]"
slogger-tui worker.jsonl api.jsonl worker.jsonl
# Equivalent module launcher:
python -m slogger.tools.tui worker.jsonl api.jsonl
```

Python 3.10–3.13 and Textual `>=8.2.8,<9` are the initial dependency range.
The storage allocation contract requires POSIX `statvfs`/`st_blocks`; durable
cache ownership also requires `flock` leases on a local filesystem. Network
filesystem lock/durability semantics are not qualified.
Installed headless and native interaction tests run on macOS with CPython 3.10
and 3.13, Textual 8.2.8; actual local emulator, Linux, SSH, and multiplexer
qualification remains in the terminal-validation slice. Core logging and Python
IXR do not require Textual, Rich, or Polars. A missing native dependency produces
an actionable `dependency_missing` diagnostic.

The screen launches while capture runs in a session-owned background worker.
Console selection and complete JSON inspection use the published captured prefix.
The heading distinguishes capturing, verification, complete, canceled, and failed
states, reports byte/record progress, and identifies failures by physical origin
when available. Esc requests cancellation and retains the incomplete prefix; Q
quits and releases the session. Input order and repeated occurrences are preserved. Each file's opening byte boundary is
established before capture; later appends remain outside this dataset. Capture
checks descriptor/path identity and rereads the opening bytes to verify their
hashes. Observed truncation, replacement, or mutation fails capture; this is an
application boundary, not an operating-system snapshot for concurrent rewrites.

UTF-8, universal newlines (LF/CRLF/CR), blank-line handling, malformed JSON and
non-object skips follow shared source decoding. A valid final object without a
newline is admitted; a malformed final line is diagnosed and skipped. Physical
lines remain separate from displayed positions and repeated-input identities.
Original application fields are untouched, including `_id` and metadata-like keys.

Use Up/Down to select records, PageUp/PageDown to move through display rows,
and Home/End to jump to the first/last record. A long wrapped record may take
several pages; clicking any continuation line selects that same original record.
Mouse wheel events scroll display rows when the terminal reports them, and
Ctrl+Up/Down provides the same route one row at a time. Tab switches panes;
F2 focuses JSON, F3 returns to the console, and Q quits. Resize retains the selected record and adapts the visible row mapping.

The focused console has temporary session controls: W toggles wrapping, T cycles
UTC time-only, UTC date-and-time, and original timestamp display, and D toggles
`duration_ms`. Its heading shows the current options. In pan mode, Left/Right
moves horizontally, Shift+Left/Right moves by a viewport width, and Ctrl+Left
returns to the start. These choices belong to the consumer and do not alter
captured records. Persisting global defaults belongs to the settings slice.

The console recognizes timestamp, level, logger, message, and canonical `span`
(with `span_name` as fallback), hides known attribution/trace/exception metadata,
and shows custom fields. Timestamp, level and a stable capped logger column
align message starts; ellipsis in those columns leaves full original values
inspectable. Generic objects are shown as JSON. The inspector retains the
complete parsed record and prettifies it with syntax colors. There is no fixed
console message, wrapped-line, or JSON preview cap.

Console virtualization uses a record ordinal and line within that record rather
than an in-memory row-height table for the whole dataset. It retains one complete
admitted record layout, at most 1025 sparse line checkpoints, and only the visible
row strips. Resizing replaces that layout; repeated navigation does not accumulate
record layouts. Working allocations remain bounded relative to the admitted
record envelope and viewport dimensions, separately from the headless encoded
record cache. This is a structural bound, not a measured total-process RSS or
1–5 GB capacity guarantee.

The inspector supports independent Up/Down, PageUp/PageDown, Home/End,
Left/Right, and Ctrl+PageUp/Ctrl+PageDown navigation. L toggles line numbers
while JSON is focused. J/K select the next/previous JSON key; a click selects
its key row, and Enter exposes its exact IXR field path for later field actions.
Bracket labels preserve literal keys: `["a"]["b"]` targets nested `b`, while
`["a.b"]` targets a single dotted key. Spaces, quotes, backslashes and Unicode
remain exact components. Keys with an empty component, or inside array items,
show guidance because current IXR Field paths cannot target them; no coercion or
invented array traversal is applied. The array's own mapping key remains usable.

I hides/shows JSON, and `[`/`]` change its width in five percentage-point steps
between 20% and 60%. P pins/unpins the inspected record. The selected console
identity and pinned inspection identity remain separate, including repeated input
occurrences; compact source names, input occurrences and physical-line locations
are shown for both. Full paths remain in the separate source-origin objects.
Moving through the console, hiding JSON, resizing, and capture progress updates
preserve the pin and inspector scroll/key selection. Selected and pinned record
counts update as the captured prefix grows; disk and browsing-cache usage remain
visible while pinned. Unpinning inspects the current console selection.

Below 90 columns the console fills the screen. F2, Tab, or I can show a full-width
JSON pane; F3 or Tab returns to the stream. Widening restores the chosen split
width. Ctrl+P opens the command palette with focus, hide/show, width, pin, copy,
and line-number controls, so a clipped footer does not strand an action.

C copies the complete inspected document, including a pinned record, through
Textual's OSC 52 terminal clipboard route. The application reports that the full
payload was sent and terminal acceptance is **unverified**. A terminal or
multiplexer may disable OSC 52 or reject large payloads; the application does not
truncate them or claim verified OS clipboard contents. Headless transports and
macOS Terminal report copy unavailable, as do transport errors. Actual local,
SSH, and multiplexer clipboard qualification remains in the terminal-validation
slice. Aggregate field actions remain a separate production slice.


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

Synchronous `Investigation.open()` remains the headless default. Use
`Investigation.open(paths, background=True)` to capture outside the caller thread;
all opening boundaries are established before that call returns. `wait(timeout)`
returns the current status, settling on complete/failure/cancellation or returning
a pending status when its timeout expires. `cancel()` requests cancellation;
`wait()` observes completion of cancellation and released writer/source handles.
The worker belongs only to its session, so old work cannot publish into another
investigation. Closing requests cancellation, joins capture, clears RAM, and
releases owned jobs and leases. Completed durable captures remain reusable.

`CaptureStatus` reports phase, published record count, processed opening bytes
through the published prefix, total opening bytes, skipped lines, and
`verified_bytes`. The verifying phase retains browseable records while exact
source-content verification runs. Capture errors return a `failed` session and
cancellation a `canceled` session, retaining admitted records and structured
diagnostics. Both remain incomplete and cannot become reusable completed captures.
Complete-dataset operations must
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
directory when `cache_dir` is omitted. Supplying `cache_dir` enables durable
verified reuse; completed captures remain while failed/canceled prefixes are removed
on close. These local handles are not a CLI/MCP transport schema.

## Initial resource envelope

All values are configurable through `ResourceLimits`. Defaults are provisional,
not measured 1–5 GB capacity or total-process RSS guarantees:

| Resource | Initial default | Contract |
| --- | --- | --- |
| Managed disk | 10 GiB | All allocated capture/index/result/staging/sidecar files, cache metadata, directory allocation, and reserved output growth |
| Browsing RAM cache | 256 MiB | Encoded records plus conservative per-entry accounting; LRU eviction |
| Source line / admitted record input | 8 MiB | Physical UTF-8 bytes, including terminator; larger lines fail explicitly |
| Working admission | 64 MiB | Decoded object, prettified JSON/line storage, four times raw bytes, and staged batch |
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
checks changed-file allocation at each publication. `writer(*paths)` provides
persistent handles with `stage`, `offset`, and explicit transactional `flush`;
failed flushes roll every member back to its previous published length. One
writer exclusively owns each file, and callers publish metadata only after a
successful flush. Buffered batches are bounded by working admission, reserved
growth remains visible in usage, and usage queries reconcile actual allocations.
Capture normally publishes batches at 64 KiB, 256 physical lines, or 50 ms of
processing, plus the first admitted record and source boundaries. A larger
admitted record is published alone. These are scheduling limits, not promised
wall-clock response times for filesystem reads or unusually expensive records.
Records, diagnostics, indexes, and progress become visible together, without
reopening or rescanning every managed file for every record. Disk exhaustion produces `resource_limit`;
failed capture preserves admitted records until close. Future indexes/results,
journals, staging, and spill jobs must use this mechanism. Durable workspaces
publish their allocations/reservations under a global process lock; private
storage remains session scoped. The default RAM candidate and practical scale envelope will be
revisited using production measurements.

Launcher flags expose `--cache-dir`, `--cache-expiry-days`, `--no-cache`,
`--storage-dir` (temporary mode), `--disk-budget-mib`, `--ram-cache-mib`, and
`--max-record-mib`. The headless API exposes all limits. Increasing the source
line limit alone does not override working/page admission.


## Durable verified cache

The native launcher uses `~/Library/Caches/slogger/investigation-v1` on macOS,
and `$XDG_CACHE_HOME/slogger/investigation-v1` on other POSIX systems (default
`~/.cache`). `default_cache_dir()` only selects that path; no import creates files.
Headless callers opt in explicitly:

```python
from slogger.tools import CacheStore, Investigation, ResourceLimits

limits = ResourceLimits(disk_bytes=10 * 1024**3)
cache = CacheStore("/my/managed/cache", limits=limits, expiry_seconds=7 * 86400)
with Investigation.open(["worker.jsonl"], cache_dir=cache.root, limits=limits) as session:
    print(session.status.cache_state, session.resources)
    outcome = cache.clear()  # this session remains protected
    print(outcome.removed_entries, outcome.protected_entries, outcome.reclaimed_bytes)
print(cache.usage)
cache.clear(expired_only=True)
```

Version 1 bundles capture, source decoding/schema, and index compatibility.
Ordered source labels, input occurrences, opening lengths, device/inode identities,
and SHA-256 of every opening byte must match. Current extent is checked even when
an unchanged cached prefix is followed by appends. Size/mtime alone never authorize
reuse. The catalog authenticates the manifest digest; all four capture data/index
files are hashed against it before reuse. Corrupt/incompatible/changed entries are
rejected and fresh capture runs, with `cache_reason` explaining rejection. This is
integrity checking for owned local cache data, not authentication against an attacker
who can rewrite both the catalog and its files.

Reuse retains the dataset identity and raw occurrences without JSON decoding or
index reconstruction. It still reads captured files and every supplied source
occurrence. `verifying_cache` is incomplete and has no browseable records;
`verified_bytes`, `cache_verified_bytes`, and `cache_total_bytes` expose that I/O.
After successful verification `cache_state` is `reused`. Cold durable completion
reports `stored`. Current record, working, page and RAM limits apply on reopen;
persisted admission maxima reject records that no longer fit, rather than exposing
an empty page as a successful dataset. The RAM cache is process local.

A SQLite catalog holds bounded allocation records and reservations; an exclusive
catalog `flock` serializes global admission. Every workspace holds a shared kernel
lease for its lifetime; clear/recovery obtains an exclusive nonblocking lease before
removing anything. Kernel release after process exit avoids PID-reuse heuristics.
Multiple reopeners share immutable capture files and own distinct job workspaces.
Completed captures expire after seven days since the last released lease by default.
Explicit clear removes inactive entries regardless of age and returns structured
removed/protected/reclaimed counts and remaining usage. Recovery removes inactive
staging and unregistered owned UUID workspaces, and reclaims crashed jobs/reservations
beside young completed captures. Active datasets and their jobs remain protected.
Only the managed `entries` namespace is reclaimed; unrelated parent files remain.

Allocation is the greater of logical size and `st_blocks * 512`, including database
free pages, current journals/WAL/spill, directories, and catalog files. Reservations
cover admitted external peaks before writing. `ManagedStorage.external_growth(path,
byte_count=...)` reserves growth, then consumes the reservation and reconciles actual
files/sidecars before checking allocation. The caller must enforce its engine's total
growth ceiling (including temporary/journal/spill peaks); SQLite tree staging uses
unpublished journal-off transactions with a page-count ceiling. Close handles before
`remove_file(path)`; active managed writers are rejected. Unmanaged external file
creation is outside the contract. Storage is bounded by the configured disk budget;
filesystem allocation granularity and metadata are included in admission. These
budgets and cache timings are not production 1–5 GB measurements or RSS guarantees.
