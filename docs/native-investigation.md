# Native investigation

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
captured records. F10 opens session settings and explicit saved defaults.

The console recognizes timestamp, level, logger, message, and canonical `span`
(with `span_name` as fallback), hides known attribution/trace/exception metadata,
and shows custom fields. Timestamp, level and a stable capped logger column
align message starts; ellipsis in those columns leaves full original values
inspectable. Generic objects are shown as JSON. The inspector retains the
complete parsed record and prettifies it with syntax colors. There is no fixed
console message, wrapped-line, or JSON preview cap.

Console virtualization uses a displayed result position and line within its record rather
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


## Filter completion

The focused filter editor shows a small scrollable syntax menu below its input.
Up/down chooses an item; Tab or a mouse click accepts it. Enter always applies
rather than accepting a suggestion. Escape dismisses the menu first; another
Escape can cancel pending work. Ctrl+Space reopens a dismissed menu. Moving
focus to another pane hides the menu, and ordinary Tab focus traversal remains
available when no choices are shown.

Choices follow the shared infix grammar: function and NOT/group starts, field
operators, typed JSON templates, AND/OR, function commas, and closing parentheses
or brackets. String operators suggest a quoted string; membership suggests an
array and scalar elements; ordering accepts a number or string; equality allows
all supported JSON types. Templates place the cursor inside quotes or brackets.
The status row explains missing operands, quoting, array separators, and invalid
types without changing the applied view. Completion replaces only the token at
the cursor and preserves the remaining draft. A response from another draft,
cursor, or generation cannot apply. The same editor can be used for an
independent scope; its completion and menu state belong to that editor.

Once capture is verified, the application builds a disk-backed index of every
supported observed path and scalar value. The status row shows index progress;
syntax choices remain available while it builds. Rare late keys, trace/span
identifiers and names are included. Field paths use their unambiguous IXR spelling;
values retain JSON types and escaping, including distinct observed `1`, `1.0`,
`true`, and `null` insertions. No-prefix scalar choices prefer frequent values.
Prefixes match literally, including `%`, `_`, backslashes and quoted text.

The menu shows small observation pages alongside grammar choices. PgUp/PgDn moves
between pages; narrowing a prefix reaches rare choices without a sampling cap.
Changing the draft, cursor or dataset invalidates the previous page. Main and any
other instance of the reusable editor can share one index while keeping separate
drafts and menu state. Escape can cancel index construction as well as other work;
use **Retry field discovery** in Ctrl+P's command palette after cancellation or
failure. A failed index leaves captured records and syntax completion usable.

IXR supports mapping paths with nonempty components. Completion does not invent
array-index paths or recursively flatten arrays.
Supported immediate scalar array elements are indexed separately for
`contains_any`/`contains_all` candidate completion. They never become scalar field
values for equality or `IN`. An array itself remains a selectable field for
structural equality and immediate-array predicates. Empty keys, nonfinite numbers,
and unsupported immediate collection/nonfinite elements have explicit counts and
guidance. Resource failures
report unavailable choices rather than silently truncating discovery.

Headless consumers call `Investigation.discover(background=True)` and observe the
`DiscoveryJob`'s dataset/request `scope`, `status` (including processed/total record
counts), `diagnostics`, `cancel()`, and `wait()`. `result()` requires complete index
construction and returns a registered `DiscoveryIndex`. `fields(prefix='',
parent=None, offset=0, limit=50)` pages exact path observations; `parent` optionally
restricts to direct components. `values(path, prefix='', offset=0, limit=50,
kinds=..., source='field')` pages typed scalar spellings and occurrence counts;
`source='array_element'` selects the separate immediate-element observations.
Prefixes refer to
canonical field/JSON value spellings. No-prefix values use descending frequency
then spelling; other pages use spelling order. Follow `next_offset` while
`has_more` to visit every choice. Scalar-field frequency counts record occurrences;
array-element frequency counts each supported immediate element, including duplicates
within one array. Repeated supplied-file occurrences count again in both lanes.
Unsupported collection/nonfinite array elements are not recursively flattened or
coerced. Index status counts them as `unsupported_elements`.

`index.complete(complete_filter(draft, cursor, generation=...), offset=0,
limit=20, cancel_event=None)` returns a `DiscoveryCompletionPage` with explicit
index scope and an extended immutable grammar response. Its optional threading
Event interrupts a superseded prefix read. Accept only a response for the current
index, exact draft/cursor/generation, and replacement span; structured consumers
need not adopt the native editor. `FilterEditor.set_discovery(index)` binds that
index to its independent asynchronous latest-request menu. This is a local operation
contract, not a CLI/MCP wire schema.

Discovery scans one admitted record and bounded path traversal at a time. Index
and complete result storage participate in managed disk admission; SQLite uses
an enforced page ceiling before each transaction, bounded cache, no mmap, and
indexed ordering without unbounded sort workspace. Collection traversal does not
accumulate the dataset or global vocabulary in RAM. Pages honor configured record
and decoded-memory limits, and may be shorter than the requested count. Every
successful index belongs to its session; close its handle to release storage, or
close the session to cancel/join operations and close all views. These operation
indexes are temporary even when the captured dataset uses durable cache reuse.
Actual process RSS/CPU and 1–5 GB performance remain qualification work.

## Main filter

F4 focuses the compact Main editor. Enter applies its draft over the complete
verified dataset; an empty draft admits every record. The status names the applied
filter separately from pending work and a changed draft. Syntax/type errors include
a line and column with repair guidance. Escape cancels pending filter work or
capture, while preserving the previous successful filtered view. Applying another
valid draft supersedes the prior request; only the latest successful request can
replace the view. Ordinary editing never applies automatically.

Dots traverse nested mappings; JSON-quoted brackets spell exact keys. For example,
`request.method == "GET"` traverses two keys, `["request.method"] == "GET"`
addresses one dotted key, and `request["with space"] == 0` mixes both forms.
Quoted components preserve spaces, quotes, backslashes and Unicode. Empty keys
and array indexes are unsupported by existing IXR field paths and produce errors.
Values use JSON syntax, preserving booleans, numbers, strings, null, arrays and
objects. Missing remains distinct from present null; booleans never become numbers.

| Operation | Examples |
| --- | --- |
| Typed comparisons / structural equality | `n >= 3`, `flag != false`, `obj == {"items":[1,true]}` |
| Scalar membership | `level IN ["ERROR","WARNING"]`, `n NOT IN [0,1]` |
| Immediate array membership | `tags contains_any ["slow"]`, `contains_all(tags, ["a","b"])` |
| Literal substring / regex search | `message contains "a.b"`, `message matches "a.*b"` |
| String prefix | `message starts_with "failed"`, `starts_with(message, "failed")` |
| Presence / absence | `exists(trace_id)`, `trace_id missing`, `missing(request.method)` |
| Logger hierarchy | `logger_prefix("service")` |
| Boolean composition | `NOT (level == "DEBUG" OR n < 0) AND trace_id exists` |

Functions also support `in`, `not_in`, `contains_any`, `contains_all`, `contains`,
`matches` and `regex` with a field then JSON operand. Boolean words and function
names are case-insensitive; NOT binds before AND before OR. `contains` composes
escaped Python regex search over the literal substring; it adds no IXR opcode.
All typed/structural decisions and regex behavior come from existing IXR builders
and the reference compiler. This captured filter path uses Python. Materialized
`QueryPlan.execute(backend="polars")` remains the explicit optional native route,
with its existing capability/dependency errors and no automatic fallback.

Filtering retains complete membership on disk in input order. Displayed positions
are separate from original dataset ordinals, input occurrences and physical source
lines. Up/Down and Home/End navigate the filtered sequence; JSON always inspects
the original record. A retained selection survives only when its identity belongs
to the new view. Pins remain independent, including when no filtered records match.


## Headless operations

```python
from slogger.tools import Investigation, ResourceLimits, parse_filter

with Investigation.open(["worker.jsonl", "api.jsonl"], limits=ResourceLimits()) as session:
    if session.status.complete:
        session.require_ready("my complete-dataset operation")
    page = session.page(0, 100)
    # Application records, origins and dataset identities are aligned separately.
    print(page.records, page.origins, page.identities)
    next_page = session.page(page.next_offset, 100)
    diagnostics = session.diagnostic_page(0, 100)
    print(session.status, session.sources, session.resources, diagnostics)
    if session.status.complete:
        job = session.filter(parse_filter('level == "ERROR"'), request_generation=1)
        view = job.wait()  # asynchronous execution; wait blocks only this caller
        if view is not None:
            filtered = view.page(0, 100)
            print(view.scope, filtered.records, filtered.origins, filtered.identities)
            # An explicit input view narrows another operation without a Main workflow.
            child = session.filter(parse_filter('message contains "timeout"'), input_view=view)
            child_view = child.wait()
            view.close()
```

Synchronous `Investigation.open()` remains the headless default. Use
`Investigation.open(paths, background=True)` to capture outside the caller thread;
all opening boundaries are established before that call returns. `wait(timeout)`
returns the current status, settling on complete/failure/cancellation or returning
a pending status when its timeout expires. `cancel()` requests cancellation;
`wait()` observes completion of cancellation and released writer/source handles.
The worker belongs only to its session, so old work cannot publish into another
investigation. Closing requests cancellation, joins capture and registered operations,
closes successful views, clears RAM, and releases owned jobs and leases.
Completed durable captures remain reusable.

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

Close is idempotent, releases session-owned jobs and RAM, and removes temporary
records, indexes and diagnostics. Use a context manager, including for
failed sessions. `storage_dir` selects the parent of a private temporary session
directory when `cache_dir` is omitted. Supplying `cache_dir` enables durable
verified reuse; completed captures remain while failed/canceled prefixes are removed
on close. These local handles are not a CLI/MCP transport schema.


`filter(expression, input_view=None, request_generation=0)` accepts IXR directly;
structured consumers need no editor. `FilterScope` includes an immutable
`ViewScope(dataset_id, view_id)`, expression, request generation and reference
backend. Each independent `FilterJob` exposes `status`, `diagnostics`, `done`,
`cancel()`, `wait(timeout)` and a successful `view`. A wait timeout raises
`TimeoutError` without canceling work. `OperationStatus` reports pending/running/
complete/cancelled/failed phases, processed and total input records, and result
records. Failure/cancellation publishes no incomplete result. There is no shared
current Main filter in the session; consumers choose which successful handle to
retain and reject outdated request generations themselves.

`RecordView` exposes `scope`, `view_scope`, `record_count`, bounded `page`,
`position_of(dataset_ordinal)` and `close()`. Membership stays in a fixed-width
disk file; pages resolve fresh original records and aligned origins/identities.
`position_of` uses bounded-memory binary lookup in preserved order. Closing a
handle releases its file after any running dependent operation releases its lease.
Closing the Investigation cancels and joins all registered jobs before releasing
views/storage. These typed local handles do not define an external transport or
handle lifetime. Shared `parse_filter`, `parse_field_path`, `format_field_path`
and located `FilterSyntaxError` are tooling exports; no native dependency is loaded.

Each reference filter executes in a package-owned Python subprocess, which reads
one admitted captured record at a time and sends at most 128 membership ordinals
per pipe message. A parent monitor owns transactional result allocation/publication
through `ManagedStorage`. This isolates Python regex evaluation from the native
UI and permits termination during pathological matches; cooperative row checks
alone would not provide that isolation. Cancellation joins the worker before
removing staging. The native consumer queues only its latest superseding request
until the previous worker has exited. No wall-time cancellation deadline or
whole-process RAM bound is claimed. Expressions have explicit working-memory
admission; interpreter/compiler/OS overhead remains separate.

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
writer exclusively owns each file; `remove_file(path)` releases inactive managed
files and reconciles their ledger. Callers publish metadata only after a
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
storage remains session scoped. Every admission checks the shared total against
that opener's configured disk budget. Shrink/release still succeeds if another
opener with a larger limit has grown the cache; growth under the lower limit fails. The default RAM candidate and practical scale envelope will be
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
rejected and fresh capture runs, with `cache_reason` explaining rejection.
An unreadable/corrupt catalog raises an actionable `cache_corrupt` or `storage_failed`
setup error; use another managed directory or `--no-cache`. The catalog is not
silently rewritten while other processes may own active work. This is
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
free pages, current journals/WAL/spill, directories, and catalog files.
`ResourceUsage.catalog_reserve_bytes` separately exposes conservative metadata
headroom (twice catalog allocation plus 64 KiB) for rollback-journal and directory/
catalog growth peaks; `managed_disk_bytes` includes this and job reservations.
Actual allocated `disk_bytes` stays distinct from that admitted headroom. Reservations
cover admitted external peaks before writing. `ManagedStorage.external_growth(path,
byte_count=...)` reserves growth, then consumes the reservation and reconciles actual
files/sidecars before checking allocation. The caller must enforce its engine's total
growth ceiling (including temporary/journal/spill peaks); SQLite tree staging uses
unpublished journal-off transactions with a page-count ceiling. Close handles before
`remove_file(path)`; active managed writers are rejected. Unmanaged external file
creation is outside the contract. Storage is bounded by the configured disk budget;
filesystem allocation granularity and metadata are included in admission. These
budgets and cache timings are not production 1–5 GB measurements or RSS guarantees.
## Complete unfiltered trace trees

B switches between the console and the complete unfiltered trace tree after
capture verification. Building runs in a cancellable background job while the
console remains usable. Esc cancels pending tree work, and a superseded request
cannot install its result. A failed or over-budget tree leaves capture usable.
An applied Main filter is explicitly unsupported in this slice; filtered ancestor
context and search integration follow separately.

Tree Up/Down selects structural rows or original record leaves; only a record
leaf changes the selected/inspected record. PageUp/PageDown and Home/End navigate
visible tree rows, Space/Enter or a structural-row click toggles its fold,
Left collapses or moves to the parent, and Right expands or enters a child.
Shift+Space folds/expands the whole tree using a default mode with bounded sparse
exceptions. Shift+Left/Right pans wide complete rows. B returns to the selected
record in the console. JSON pins, source occurrence identity, and F2/F3 pane
focus survive these changes; structural placeholders never become record IDs.

Trace identity is a nonempty string `trace_id`; span identity is that trace plus
a nonempty string `span_id`. No identifier coercion is applied. Canonical `span`
is the label, with external `span_name` fallback; conflicting observed names are
marked and all original contributor records remain available. Roots, siblings
and leaves use supplied-source first appearance and record ordinal, not time.
Untraced or invalidly identified records remain accessible with explicit states.
A referenced absent span is a placeholder with no fabricated contributor record.

A canonical `event="span.start"` with omitted parent establishes root evidence.
Ordinary absent parents mean parent not observed; explicit null, empty, invalid,
and contradictory parents retain distinct uncertainty. Consistent nonempty IDs
link only within their trace. Self/long cycles are broken for display and marked
on their members; cycle descendants retain their own evidence. No records are
lost or duplicated by these arrangements.

Only canonical start/end events count as lifecycle evidence. Repeated starts or
ends remain repeated occurrences and make a unique lifecycle summary conflicting.
No events means unavailable; one missing endpoint means incomplete, with no
running/completion inference. A unique start/end pair may summarize only a valid
observed `ok`/`error` status and nonnegative finite numeric `duration_ms` (never a
boolean). Invalid end evidence is conflicting. No timestamp-derived duration or
trace-duration metric is introduced. Contributor pages expose complete original
records and separate origins/identities to inspect every disagreeing value.

Headless `Investigation.build_tree(background=True)` returns a `TreeJob` with
immutable dataset/request `TreeScope`, status, cancel/wait/result/close operations.
`result()` requires completion and returns `TraceTree`: bounded `children`,
`record_page`, `row`, `node_for_record`, and indexed sibling/edge-child navigation.
`TreePage.next_offset` reflects actual delivered rows; `has_more` signals another
page. Original record pages keep dataset ordinals separate from evidence-page
positions. Closing the session cancels/joins jobs and closes tree handles before
releasing storage. Tree data has no Textual/Rich dependency or fold preferences.

The SQLite index is unpublished staging until complete. It uses a bounded page
cache, disables mmap and journal/WAL, avoids engine sorts/grouping workspaces,
and admits a main-file page ceiling before every transaction. SQLite rejects
larger growth before publication; all allocation is reconciled through managed
storage. Cancellation/failure closes handles before reclaiming staging. Functional
cycle walks keep visitation/path state on disk without recursive Python stacks
or a per-trace in-memory node collection. Pages and the native visible row window
remain bounded. These structural limits are not measured total-process RSS,
1–5 GB scale, real emulator, SSH, or multiplexer qualification.

## Literal record search

F7 focuses the compact Find row. Typing highlights decoded text immediately in
visible console content without moving the selected record. Enter/Shift+Enter
navigate to the next/previous matching record relative to the cursor, with wrapping;
F8/Shift+F8 provide the same routes without entering the search field. Search keeps
surrounding records in the stream and respects the successful applied Main filter.
Counts describe matching records, not the number of text occurrences. The complete
count becomes available after a 150 ms debounce and cancellable background scan.

Click Console/Full, Aa or Word, or use Alt+S/Alt+C/Alt+W in Find, to choose the scope,
case sensitivity and whole-word behavior. Console examines complete original field
names/values before column truncation, timestamp formatting, wrapping or panning.
Duration visibility and canonical-span/fallback policy are included. Full examines
all decoded names and leaves, including metadata, nested objects and arrays;
matching hidden content is also highlighted in the complete JSON inspector.
Search never joins unrelated leaves or treats JSON quotes, punctuation and escapes
as input text. Non-string leaves use their JSON scalar representations. A decoded
newline is a newline; the two literal characters backslash+n only match when those
characters actually occur in data. JSON highlights map decoded matches back onto
their displayed escape sequences.

Case-insensitive matching uses Unicode casefold, including complete expansions
such as `ss` matching `ß`; it never accepts part of one expanded scalar. Whole-word
edges are the beginning/end of a leaf or adjacent characters outside Unicode
alphanumeric characters, underscore and combining marks. No Unicode normalization,
regex, or whole-field-equality interpretation is implied. Highlight colors have
explicit contrasting foreground/background, and only visible viewport ranges add
match styling even when one record contains many repeated occurrences.

A changed search/options/console visibility or Main request invalidates the old
match scope. Native generations discard superseded results after worker cleanup;
Main-pending work waits for a successful filter or returns to the retained view
on failure/cancellation. Empty Find clears immediately. Escape cancels pending
search without changing the stream, selection or JSON pin. Tree search and filtered
ancestor revelation remain ticket15; this slice labels those combinations as
unavailable instead of displaying misleading results.

The headless `Investigation.search(SearchOptions(...), input_view=None,
request_generation=0)` gates complete capture and returns a `SearchJob` with frozen
`SearchScope`, structured `OperationStatus`, diagnostics, cancellation, `done`, and
`wait(timeout)`. A timeout raises `TimeoutError` without cancellation. Only a complete
successful job publishes `SearchResult`: bounded original-record pages, matching
`record_count`, ordinal `position_of`, `neighbor(ordinal, previous=False)` with wrap,
and `close()`. Dataset ordinals, source origins and repeated input occurrences remain
separate from match-page positions. Index membership is an ordered, fixed-width
managed disk spool, never a list proportional to dataset size in RAM.

Headless full-record scope is explicit. Console scope additionally requires a
structured `SearchProjection` supplied by the consumer: primary/hidden/include
fields, canonical/fallback pairs and generic-object policy. It imports no terminal
libraries or native display defaults. Input views are leased while scanning;
independent result handles stay valid until closed. Cancellation/close joins workers
before reclaiming files. Resource/OS/cleanup errors produce settled status and retain
captured data; unreclaimed allocations remain accounted until owner cleanup.
Working admission bounds one decoded record and folded text, plus a small write
batch. This is not a whole-process RSS, scale-latency, or real terminal qualification.


## Exact selected-field value counts

Click a console value or key to select its exact field; Enter opens complete counts.
Ctrl+click or a double click counts directly. Alt+Left/Right cycles fields on the
selected console record; Enter counts that target. A displayed
span label targets canonical `span` when present and otherwise `span_name`, matching
the JSON inspector's exact path. In JSON, select a key with j/k or a click and press
Enter. F5 opens the lower pane's field editor; enter `request.method` or `["literal.key"]`
to distinguish a nested path from a literal dotted key. F6 focuses counts; Up/Down,
PageUp/PageDown, Home/End and Left/Right reach every group and long value. Ctrl+A or
the command palette toggles the pane. The inspector remains independently pinned.

Counts follow the successfully applied Main filter. The exact input population is
its immutable result view intersected with `exists(selected field)`; missing selected
fields contribute nothing. Explicit null, zero and false remain present, and repeated
input occurrences count again. Scalar grouping preserves bool/number distinction,
compatible `1`/`1.0` and signed-zero groups, huge adjacent integers, and the first
observed value and group order. Collections and nonfinite values fail with type
guidance. Public `count_rows()` continues to count every upstream row unchanged.
An empty present population has zero categorical groups.

Pending counts show their requested field/Main label alongside the previous successful
scope. Following Main preserves unsubmitted field drafts and hidden-pane visibility.
A failed or canceled replacement retains the old result and its own label;
a superseded job cannot publish. Esc cancels pending operations, leaving the successful
view and counts usable. Numeric summaries, multiple group fields and independent
aggregate filters remain subsequent slices.

`Investigation.count_values(path, input_view=None, request_generation=0)` accepts an
explicit tuple of nonempty mapping path components. It returns an `AggregateJob` with
structured `scope`, `status`, `diagnostics`, `done`, `cancel()` and `wait(timeout)`;
a timed wait raises `TimeoutError`. A successful complete `AggregateResult` exposes
`record_count`, `scope`, `page(offset, limit)` and `close()`. `AggregatePage.records`
contains `{value, count}` rows, with separate aligned `None` origins, actual
`next_offset` and `has_more`. No synthetic fields are added to captured application
records. `FieldBinding` is an out-of-band tooling path binding, reusable by later
reducers without changing literal-key QueryPlan grouping.

Jobs lease their explicit input membership, so closing the caller's view does not
remove a running operation's input. Session close cancels/joins jobs before releasing
results and storage. All groups remain on managed disk and are paged in insertion
order; no sampled eligible-record or displayed-group limit is used. SQLite staging
uses an admitted main-file page ceiling, disabled mmap/journal/WAL, a bounded page
cache and indexed key lookup without sorting workspaces. Each bounded transaction
reserves conservative B-tree/overflow growth through the shared storage ledger;
failure closes the database before removing its unpublished file. Selected values
undergo serialization/working admission after presence, and every delivered row
obeys page memory limits. These admission bounds exclude interpreter/allocator and
OS overhead and are not a whole-process RSS or 1–5 GB qualification claim.


## Session settings and saved defaults

F10 or **Settings** in Ctrl+P opens a compact keyboard-accessible view. Tab and
Shift+Tab move through the scrollable options; Space toggles switches and Enter
opens a select. Options cover dark/light theme, console/tree wrapping, timestamp
mode (including the date), optional duration, JSON line numbers and visibility,
JSON width from20–60%, aggregate-pane visibility, all ResourceLimits, and cache
inactivity expiry. A long wrapped tree record supports PageUp/PageDown through
its continuation lines; row selection and folds retain their original identities.

**Apply session** (Ctrl+Enter) validates the entire draft before changing effective
values. These changes are temporary. **Save defaults** (Ctrl+S) writes the current
*applied* session values atomically, including presentation adjustments made with
the normal keyboard controls. Unapplied form edits are not saved. Esc/Close returns
to the prior pane. Saving writes preferences only; Main/aggregate queries, search
text/options, cursor positions, pins and navigation history are never persisted.

Saved defaults are read by the native launcher. macOS uses
`~/Library/Application Support/slogger/tui-preferences.json`; other POSIX systems
use `$XDG_CONFIG_HOME/slogger/tui-preferences.json`, falling back to
`~/.config/slogger/tui-preferences.json`. Path selection/import/missing-default
loading create no files. `--preferences-file PATH` chooses an explicit location.
Malformed or unsupported defaults report `preferences_invalid`; they are not
silently rewritten. Explicit launch resource/expiry options override the matching
saved defaults, and unspecified values retain them. Existing cache roots/leases
never move when presentation or budget preferences change.

Usage distinguishes actual allocated managed disk, job reservations, catalog
reserve and their total against the effective disk budget. Encoded browsing-cache
usage is separate from total-process RSS. **Clear expired** uses the current expiry;
**Clear unused** removes inactive entries regardless of age. Both protect active
leases across processes and show removed/protected/reclaimed totals. Temporary
mode has no reusable cache to clear. Dark/light palettes, syntax colors, selection,
errors and live highlighting have native headless coverage; that is not actual
emulator/SSH appearance qualification.

Headless consumers use the same live resource operation:

```python
from dataclasses import replace

with Investigation.open(["api.jsonl"], cache_dir="/tmp/owned-cache") as session:
    effective = session.configure_resources(
        limits=replace(session.limits, ram_cache_bytes=128 * 1024**2),
        cache_expiry_seconds=3 * 86400,
    )
    print(effective.limits, effective.cache_expiry_seconds, effective.usage)
```

`configure_resources()` returns immutable `ResourceConfiguration`. Session,
storage and active durable owner limits change coherently under lifecycle/page/
storage/catalog locks. A disk decrease below actual allocation plus reservations,
or record/working/page decrease that cannot admit the captured dataset, raises
`resource_limit` and preserves prior effective values. Execution/page/record/page-
count decreases require settled capture/jobs and closed result readers; otherwise
`configuration_busy` explains the protected earlier memory snapshots. Increases
and encoded RAM-cache changes may apply while work runs. RAM shrink immediately
evicts encoded entries; existing worker/SQLite working-memory snapshots are never
retroactively shrunk. Future operations/refresh opening use the effective limits.
Expiry must be finite and nonnegative; resource limits are positive integers.
