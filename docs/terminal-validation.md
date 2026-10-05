# Terminal validation

Use this exercise on the reviewed source, locally and through your existing SSH
workflow. Actual emulator, Linux, SSH and multiplexer qualification is **pending**.
Headless native tests and a PTY smoke establish software behavior and process
transport separately; they do not establish gesture delivery, appearance or
clipboard acceptance. The earlier Codex after-tab mouse report remains
unreproduced and unattributed. Historical prototype results do not qualify this
production application.

## Install the reviewed source and prepare the demo

Install **this repository**: the PyPI name `slogger` belongs to an unrelated
package. Python 3.10–3.13 and Textual `>=8.2.8,<9` are the initial dependency range;
endpoint checks currently use macOS CPython 3.10/3.13 and Textual 8.2.8. Optional
Polars is unnecessary for this Python workflow. Capture requires POSIX
`statvfs`/`st_blocks`; durable caches additionally require local-filesystem `flock`.
Network-filesystem lock/durability behavior remains unqualified.

Use an existing correct environment, or from the reviewed checkout:

```sh
python3 -m venv ./terminal-env
./terminal-env/bin/python -m pip install -e '.[tools-tui]'
python3 examples/investigation_demo.py ./tui-demo
./terminal-env/bin/python -m slogger.tools.tui \
  --no-cache --preferences-file "$PWD/tui-demo/preferences.json" \
  "$PWD/tui-demo/application.jsonl" "$PWD/tui-demo/worker.jsonl"
```

The installed entry point `slogger-tui` is equivalent. `--no-cache` isolates
capture storage; the explicit preferences path isolates intentional Save defaults.
Missing Textual reports `dependency_missing` and the required extra. Query, search
and navigation history is session-only; preferences save presentation/resource
settings only. Keep output in a task-owned directory. The stdlib demo generator
refuses to overwrite its three files, uses ASCII messages and records expected
counts and SHA-256 identities in `manifest.json`.

The integration branch may be local and unpublished. To use the same source on an
existing remote host, transfer a tracked source archive plus its revision and
SHA-256 record with your usual SSH/file-transfer workflow; no push or new remote
access is necessary. The person preparing the reviewed build can create them:

```sh
# Run in the reviewed checkout; replace REVIEWED_COMMIT with its exact commit.
git rev-parse REVIEWED_COMMIT > /path/to/task-output/revision.txt
git archive --format=tar.gz --prefix=slogger-source/ \
  -o /path/to/task-output/slogger-source.tar.gz REVIEWED_COMMIT
```

Compute/verify the archive digest:

```sh
python3 - <<'PY'
import hashlib
from pathlib import Path
path = Path('/path/to/task-output/slogger-source.tar.gz')
print(hashlib.sha256(path.read_bytes()).hexdigest())
PY
```

Record that digest alongside `revision.txt`. Verify the transferred digest before
extracting; from the extracted `slogger-source/` directory use the setup above.
Its static setuptools version supports installation without `.git`. The archive
contains tracked source and the generator; environment, caches and log datasets
are not bundled. The checkout route remains available if that reviewed commit is
already present remotely. No credentials, hostname, provisioning or download is
assumed by this exercise.

## Controls and fallbacks

Letters below assume the corresponding viewport has focus; inside an input they
edit the draft. Some terminals reserve function/Alt combinations: use Ctrl+P's
command palette and clickable controls, and report what the terminal delivered.

| Area | Keys and routes |
| --- | --- |
| Focus/layout | Alt+2 JSON; Alt+1 stream; Tab/Shift+Tab between panes; Ctrl+Tab/Ctrl+Shift+Tab from inputs; I JSON visibility; `[`/`]` width; Ctrl+P palette; Q quit outside inputs |
| Flat stream | Up/Down select; PgUp/PgDn display rows; Home/End; Ctrl+Up/Down one display row; W wrap; T timestamps; D duration |
| Flat horizontal pan | Left/Right; Shift+Left/Right viewport width; Ctrl+Left start, with wrapping off |
| JSON | Arrows, PgUp/PgDn, Home/End; Left/Right and Ctrl+PgUp/PgDn pan; L lines; J/K select keys; Enter aggregate key; P pin |
| Main filter | F; Enter apply and return to stream; syntax errors stay in editor; Up/Down suggestions; Tab/click accept; PgUp/PgDn observation pages; Esc dismiss/cancel and return to stream; Ctrl+Space reopen |
| Search | /; Alt+S Console/Full; Alt+C case; Alt+W word; Enter next and return to stream; Shift+Enter previous and return; N/Shift+N from panes; empty text clears |
| Tree | B flat/tree; arrows/paging/Home/End; Left collapse/parent, Right expand/child; Space/Enter fold; Shift+Space fold/expand all; Shift+Left/Right pan |
| Aggregate | A field; Alt+3 results; arrows/paging/Home/End and Left/Right pan; M metrics, then Tab grouping; Ctrl+A pane; palette **Edit aggregate grouping** |
| Independent scope | Ctrl+D/Detach copies applied Main; Enter applies Scope; Reattach button or palette **Reattach aggregate to Main** |
| Exact field selection | Console Alt+Left/Right then Enter; click then Enter; Ctrl+click/double-click direct aggregate; JSON J/K/key click then Enter |
| Settings | Comma; Tab/Shift+Tab; Space switches; Enter selects; Ctrl+Enter Apply session; Ctrl+S Save applied defaults; Esc/Close |
| Refresh | Ctrl+R or palette **Refresh sources**; Esc cancels while keeping complete prior results |
| Copy | C or palette Copy JSON sends full inspected/pinned JSON via OSC 52; **sent is not accepted** |

F2–F10 remain compatibility aliases. Shortcut hints appear only in the bottom
footer and change with focus; typed drafts must remain visible in both themes,
and completion must not cover either input row.

Ordinary wheel moves vertically. Shift/Ctrl-modified wheel is left to Textual's
horizontal handling in stream, tree and aggregate panes; keyboard pan remains
available independently. Whether a terminal emits those gestures is a manual
result. Headless transports and macOS Terminal report clipboard unavailable;
other terminals/multiplexers may reject OSC 52 or its payload size. Paste copied
JSON into a task-owned scratch editor to verify acceptance separately from the
application's sent/unavailable/error status.

Source C0/DEL/C1 controls are displayed visibly rather than sent as source terminal
commands. Raw console text preserves line breaks and expands tabs; JSON/query
spellings use equivalent escapes. Literal input drafts retain their exact value
and cursor/click indices while controls use single-character visible glyphs.
Original records, full JSON copying, field paths and decoded search semantics stay
unchanged; ordinary Unicode stays readable. Source escape spellings themselves do
not introduce search matches.

## Exercise locally, then over SSH and an available multiplexer

Start wide; narrow to about 65×30, then widen. Record actual dimensions. Each fresh
fixture starts with 64 records: application 27, worker 37. Trace-01 crosses the file
boundary; application physical line 22 has a wide message. Sparse, null, boolean,
array, nested and literal dotted fields have independent expected totals below.

1. **Browse and inspect.** Wait for complete 64. Exercise arrows, paging, Home/End,
   the application27 → worker1 boundary, Alt+2/Alt+1, Tab/Shift+Tab, I and brackets.
   Keep moving beyond one viewport: the cursor stays near the lower edge while
   the view scrolls by rows, with matching behavior near the upper edge.
   Verify the highlighted pane heading and lower Focus label agree after keyboard
   and mouse focus changes. Use Ctrl+Tab from each editor to return to a pane.
   Select the wide record; use W and keyboard pan, inspect its complete JSON tail, and pin with P.
   Browse/resize/hide/show JSON: the pin stays on its original occurrence. Unpin.
2. **Filter, completion and paste.** F; apply `tenant = "north"` using one Tab
   completion and one mouse completion → 32. Edit an unapplied south draft: the
   stream stays north. Valid Enter returns focus to the stream; arrows and F or /
   work immediately. Apply invalid `tenant =`: repair guidance retains north and
   focus stays in the editor. One Escape leaves it for the stream, hides choices
   and cancels pending work without applying or clearing the draft.
   Paste/apply the valid north expression. Both `=` and `==` use typed IXR equality;
   `level = "ERROR" and duration_ms >= 300` is accepted and yields 0 in this fixture
   because its ERROR rows lack duration_ms. Clear Main and apply → 64.
3. **Search and tree.** / `retry` → 8 matching records; typing highlights without
   moving selection. Enter/Shift+Enter navigate and wrap; N/Shift+N also work
   from panes. Enter returns focus to the stream even if the scan is pending; its
   navigation completes when matches arrive. Search `trace-01`: Console 0,
   Full 16. Toggle case/word. Alt+1 then B, fold a node/all nodes; navigation reveals
   folded matching paths. Apply `level = "WARNING"` → 4 admitted records; labeled
   Ancestor context must not inflate search or aggregates. Clear Main/apply.
4. **Aggregate scopes.** Main north/apply. Alt+1, A `response_ms`, Enter; Alt+1, M `count, sum`,
   Enter → 11 / 4080. Ctrl+D copies applied north. Main south/apply → 32 south;
   independent result remains 4080. Reattach → 11 / 4101. Clear Main/apply. Group
   by `tenant as area` → north 11/4080, south 11/4101. Clear grouping. Alt+1, A `coupon`;
   Alt+1, M `values` → WELCOME 7/null 6; 51 missing excluded. Exercise field selection
   as well as typing; `["order.total"]` addresses one literal key. Alt+3 at narrow
   width must expose the result and keyboard paging/pan.
5. **Mouse, focus and tab return.** Click records/JSON keys/folds; ordinary wheel;
   modified wheel/horizontal gestures where available. Repeat keyboard equivalents.
   Switch another terminal tab/app and back, then repeat click/wheel. Report the
   Codex after-tab case explicitly if tried; do not infer a cause from old reports.
6. **Clipboard and preferences.** Pin, C, record sent/unavailable/error; paste into
   a scratch editor and independently report accepted yes/no/untested. Use comma
   from a pane to test
   dark/light, wrapping/time/duration, JSON lines, pane visibility/width. Apply
   session; quit/reopen and verify it was temporary. Save defaults explicitly;
   reopen and verify persistence. Filters/search/history reopen empty. Return to
   desired settings, clear Main/grouping, and use response_ms with count,sum.
7. **Refresh success and restoration.** Before refresh expect 64 and 22/8181.
   Pin an unchanged record, optionally fold its tree, and leave an unsubmitted
   Main draft `tenant = "south"`. In a second shell, from the source checkout:

   ```sh
   python3 examples/investigation_demo.py ./tui-demo --append
   ```

   The running capture remains 64 until Ctrl+R. During capture/staging, its old
   complete views stay usable. Successful replacement gives 65 and 23/8281; the
   unapplied draft, verified pin, folds and presentation settings remain. Main
   north after this append has 33 rows and response_ms 12/4180. Cancel a further
   refresh with Esc while its pending heading is visible; old results must remain.
   If it finishes before Esc, report cancellation **not observed**, not passed.
8. **Refresh failure and retry.** Only inside this task demo, temporarily rename
   worker.jsonl to worker.saved.jsonl in a second shell. Ctrl+R must report failure
   while the prior complete 65-record investigation remains usable. Restore the
   original filename and retry Ctrl+R successfully. If source records were changed
   or removed, selection/pin restoration must explain unverifiable identities;
   original JSON equality alone is not proof. A cleanup_failed report retains
   accounted storage; Ctrl+R retries cleanup before another refresh.
9. **Remote combinations.** Use the same reviewed revision and fresh demo over
   the user's existing SSH host, then an available multiplexer. Repeat 1–8. Report
   actual local/remote OS, terminal, TERM and multiplexer/version, delivered keys,
   gesture/clipboard differences and usable latency. An unavailable combination
   remains pending; no new host, credentials or access are requested implicitly.

A separate durable-cache exercise can replace `--no-cache` with
`--cache-dir "$PWD/tui-demo/cache"`: reopen to see verified reuse, and try Settings
clear while the dataset is leased. Active datasets must remain protected. Do not
use the deliberately control-bearing automated regression inputs in this ordinary
manual demo.

## Evidence and report

| Environment/evidence | Status | Meaning |
| --- | --- | --- |
| macOS CPython 3.10/3.13, Textual 8.2.8 headless native | Automated checks recorded with exact revision in implementation notes | Installed operations, rendered text, native input/event semantics; no emulator claim |
| Base-only environment | Missing extra produces dependency_missing | Optional UI stays separate from logging/headless tools |
| POSIX PTY | Smoke recorded separately with exact revision | Process start, resize/navigation/exit; no rendered appearance/gesture/SSH claim |
| Ghostty/local emulator | Pending production report | Prototype evidence does not qualify current workflow |
| Codex embedded terminal | Pending production report | Historical tab-return mouse failure remains unattributed |
| Linux, SSH, multiplexer | Pending production report | No platform/clipboard/latency guarantee from headless or PTY evidence |

Send one report per actually tried combination, including skipped/unavailable
cases. Keep hostnames, credentials and private log contents out of the report.

```text
Reviewed source revision / Python / Textual:
Local OS / terminal+version / TERM / dimensions:
Remote OS / multiplexer+version, or unavailable:
1 browse/JSON/resize/pin:
2 filter/completion/paste/errors:
3 search/tree/context:
4 aggregates/detach/reattach:
5 mouse/wheel/tab return; working keyboard fallback:
6 clipboard sent|unavailable|error; accepted yes|no|untested:
6 theme/settings/session-only history:
7 refresh success/cancel/restoration (cancel unobserved if too fast):
8 refresh failure/retry:
9 remote delivery/latency and skipped cases:
```

Required actual environments stay pending until reported. Fonts/colors and gesture
support can differ; identical appearance is not promised. See the
[native guide](native-investigation.md) for complete behavior and the
[architecture](tools-architecture.md) for headless/consumer ownership.
