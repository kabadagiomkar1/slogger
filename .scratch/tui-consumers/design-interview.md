# TUI design interview

Status: resolved

## Accepted direction

- Layout A: main console stream and toggleable right JSON inspector.
- Supplied finite files, initial concatenated view, source separators and origin
  awareness, compact console rows, full record inspection.
- Flat and trace/span tree views with folding and ancestor context.
- Tree siblings and records preserve supplied-file order and first appearance,
  consistent with the initial concatenated console view.
- Record search is navigation over records admitted by the main filter.
- Console-field/full-record search scopes, case sensitivity, whole-word option,
  next/previous matches, and keyboard routes for mouse interactions.
- Filter editor completion covers syntax, keys, and typed values.
- Field aggregates follow the main filter by default and can detach their scope.
- Presentation preferences have global defaults and session adjustments.
- Input scale: support investigations totaling 1–5 GB; typical files are
  approximately 100–200 MB. This is a scale target, not a measured performance
  or memory guarantee.
- One stable investigation dataset shared by views until explicit refresh.
- Capture the investigation dataset in disk storage with a RAM
  cache for browsing. RAM-only storage was considered; predictable memory use
  for 1–5 GB takes priority over retaining the full decoded dataset in RAM.
  See [the accepted dataset decision](../../docs/adr/0002-stable-tui-investigation-datasets.md).
- Compact infix filter expressions such as
  `level = "ERROR" and duration_ms >= 300`, translated into IXR.
- Field paths use dots for ordinary nested traversal and quoted bracket
  components for exact object keys. Examples: `request.method`,
  `["request.method"]`, `request["method.code"]`, and `["http status"]`.
  Autocomplete distinguishes nested fields from literal keys and inserts the
  appropriate spelling.
- Browse captured records progressively while dataset capture continues,
  with an explicit incomplete-loading indication.
- Console-scope record search examines complete names and values of fields
  included in the console view, regardless of display truncation. Full-record
  search examines all field names and values, including metadata and exceptions.
- Establish each supplied file's capture boundary at investigation start;
  later appends appear only after explicit refresh.
- During capture, allow console browsing and JSON inspection. Full-dataset
  search, filtering, trees, and aggregates wait for complete capture.
- Refresh retains main/independent filters, search, pane settings, and aggregate
  configuration. Restore selected/pinned records only if they can be verified
  as the same records; report disappeared or changed records explicitly.
- Filter syntax uses `in`, `not in`, `contains_any`, `contains_all`, literal
  substring `contains`, regex `matches`, `exists(field)`, `missing(field)`, and
  `logger_prefix(name)`. Parentheses and `not` are supported; precedence is
  NOT, then AND, then OR. Preserve IXR's existing typed/missing/null semantics.
- Reconstruct traces across supplied files by trace ID, with spans identified
  by trace ID plus span ID. Names are labels. Keep records lacking sufficient
  trace information accessible separately.
- Mark incomplete/conflicting spans, retain all source records, and summarize
  only unambiguous evidence. Missing parents have placeholders; conflicting
  relationships must not imply a reliable hierarchy.
- Run operations in the background and keep navigation responsive. New
  operations supersede outdated work; stale completion cannot overwrite a
  newer result. Pending filters leave the last successful view and applied
  filter visible; Esc cancels pending work without discarding that view.
- Autocomplete uses the whole investigation dataset. Show small prefix-matched
  lists, favor common values without a prefix, and allow access to all observed
  scalar values, including rare IDs, through narrowed prefixes. The completion
  index may use temporary storage rather than keeping every value in RAM.
- Capture failures stop capture with actionable diagnostics. Initial partial
  data remains available for browsing/inspection and explicitly incomplete;
  failed refresh keeps the previous complete dataset usable until a successful
  replacement. Malformed JSON follows backend skipping/diagnostic behavior and
  preserves physical source-line numbering.
- Retain completed datasets in a bounded reusable disk cache across launches.
  Apply a configurable storage budget and inactivity expiry; protect datasets
  in use, clean failed/abandoned captures, and expose usage and a clear-cache
  action. Verify source contents before automatic cache reuse. Start with a
  provisional 10 GB total managed disk budget, including indexes and staging,
  and seven-day inactivity expiry. RAM cache size is configurable and may be
  increased; its exact default awaits measurement, with 256 MiB only an initial
  candidate. These are not total-process-memory or measured scale guarantees.
  Persist global settings;
  keep query/search/navigation histories within the current session initially.
- Clicking a numeric field starts a summary with count, sum, mean, min, and max;
  clicking a categorical field starts grouped counts. A small aggregate editor
  selects grouping fields and metrics. Follow the main filter by default;
  detaching copies the current filter into an independently editable scope.
  Aggregates count record occurrences, with no implicit span deduplication or
  inferred trace durations. Preserve backend missing/null/type behavior.
- The next deliverable is a focused native Textual prototype: optional
  dependency, real-file paging and JSON inspection, panes and navigation,
  representative tree/filter interactions, and measured cold/warm opening and
  memory at 1–5 GB. Actual local-terminal and SSH behavior require validation.

Primary visual evidence: `codex/tui-visual-prototype`, recorded in
[the prototype issue](issues/01-visual-prototype.md).

## Design tree

Settled first frontier:

1. Expected input scale and performance priorities.
2. Dataset consistency during an investigation and explicit refresh behavior.
3. Filter language style, preserving the full IXR filter semantics.

Current frontier: empty. The user confirmed the complete shared design and
authorized the focused native prototype.

Settled in round 2:

4. Temporary session storage with a RAM cache.
5. Browse progressively during capture.
6. Dots for nested traversal; quoted bracket components for exact object keys.
7. Search includes complete console-field names/values in console scope and
   all field names/values in full-record scope.

The complete shared design is confirmed. The focused native prototype and its
evidence are recorded in [the native prototype issue](issues/02-native-prototype.md).
Performance measurements and native-terminal validation belong to the chosen
prototype; they are not established guarantees from this interview.

## Current facts

The existing backend accepts finite sources and materializes query results.
Repeated file queries reopen their sources, so a stable investigation dataset
needs an explicit consumer contract. There is no public incremental result,
progress, cancellation, JSON query loading, or trace reconstruction interface.
These are implementation facts, not decisions imposed on the interview.

Textual's upstream metadata supports Python 3.10 and 3.13. Its input APIs
support keyboard and mouse interaction, including horizontal wheel events
when reported by the terminal, and applications can run over SSH. Its Line
API can render viewport rows from a paged dataset; this is a candidate design,
not evidence of acceptable performance at 5 GB. The stock DataTable retains
added cell data, so efficient rendering alone does not establish bounded
memory. Headless tests cannot establish actual terminal/SSH interaction.
Sources: [metadata](https://github.com/Textualize/textual/blob/main/pyproject.toml),
[input](https://textual.textualize.io/guide/input/),
[SSH support](https://textual.textualize.io/),
[Line API](https://textual.textualize.io/guide/widgets/#line-api),
[DataTable source](https://raw.githubusercontent.com/Textualize/textual/main/src/textual/widgets/_data_table.py),
[testing](https://textual.textualize.io/guide/testing/).

## Round 1

Q1: 1–5 GB is more than enough and the user's general operating size; typical
files are around 100–200 MB.

Q2: Stable dataset until explicit refresh.

Q3: Infix expression style, e.g. `level = "ERROR" and duration_ms >= 300`.

The user did not specify quantitative startup, memory, or query-time limits.
These remain open and must not be presented as accepted guarantees.

## Round 2

Q4: User requested an explanation of the meaning and implications. Disk
storage is not approved.

Q5: Browse progressively. Enabling global operations during capture remains
to be specified; the earlier recommendation was to wait for complete capture.

Q6: User requested concrete examples of the recommended path syntax. The
examples were provided; user then accepted the recommendation.

Q7: Accepted the recommended search behavior, including untruncated console
fields and field names as well as values.

Q4 follow-up: User asked about speed but repeated "Temporary disk storage" in
the comparison. Clarification requested: RAM-only versus temporary disk, or
startup/shutdown overhead. Disk storage is still not approved.

Q4 clarification received: The user is comparing RAM-only storage with
temporary disk storage. Explain expected runtime tradeoffs and the proposed
disk-backed dataset with an in-memory browsing cache; no performance has been
benchmarked and the storage decision remains open.

Q4 decision received: Temporary disk storage plus a RAM cache.

## Round 3

Q8: Accepted opening boundaries. Capture only the portion of each file that
existed at investigation start; later additions require explicit refresh.

Q9: Accepted progressive browsing and inspection, with other operations gated
until capture completes. Loading progress must be explicit.

Q10: Accepted preservation of investigation state across refresh. Verify record
identity before restoring cursor/pins; indicate changed/disappeared records.

Q11: Accepted word operators and the proposed presence/logger functions,
parentheses, NOT/AND/OR precedence, and existing IXR semantics.

## Round 4

Q12: Accepted trace joining by trace ID across files, spans scoped by trace ID
plus span ID, and separate access to records without sufficient trace identity.

Q13: Accepted explicit incomplete/conflicting presentation, source-record
retention, conservative summaries, and missing-parent placeholders.

Q14: Accepted background operations, superseding outdated work, stable prior
successful views during pending filters, Esc cancellation, and stale-result
protection.

Q15: Accepted whole-dataset completion, small prefix-matched lists, common
values first without a prefix, and temporary completion storage as needed.

## Round 5

Q16: Accepted recommended failure behavior, including preservation of a prior
complete dataset on failed refresh and explicitly incomplete initial captures.

Q17: Settings-only persistence seemed acceptable, but user raised the repeated
cost of recreating temporary storage when reopening the same supplied files,
and asked how to avoid storage/memory leaks. Persistent dataset reuse is not
yet approved. Explain bounded reusable cache versus discard-on-exit, including
source validation costs and explicit older-snapshot semantics.

Q18: User requested more detail and examples. Aggregate-editor scope is not
yet approved. Clarify without advancing to the next round.

Q17 clarification accepted: retain completed datasets in a bounded reusable
disk cache, with budget, expiry, active-dataset protection, failed/abandoned
capture cleanup, usage visibility, and clear-cache action. Explain that source
verification may still read the full files even when decoding/index creation
can be reused. Exact speed improvements require benchmarks. Persist settings;
session histories remain transient initially.

Q18 clarification accepted: numeric summary and categorical grouped-count
defaults, configurable grouping and backend metrics, main-filter following by
default, and detached scope initialized from that filter. Examples compared
all five records (duration mean 236) with ERROR records (mean 430), grouping
by logger/level, and detachment while changing the main filter. Each record
occurrence contributes; reductions retain existing backend null/type rules.

No production implementation has started. The user confirmed the complete
shared understanding after round 6; native prototype work is authorized.

## Round 6

Q19: Recommend content verification before automatic cache reuse; alternative
trusts file size/modification time and can miss changes. Full reading may
remain necessary; avoided decoding/index work needs measured benefit.

Q20: Recommend provisional configurable defaults: 256 MiB browsing RAM cache,
20 GiB total managed disk budget including indexes and staging, and seven-day
inactivity expiry. These are not process-memory or supported-scale guarantees.
Protect active entries; report insufficient space when no unused entries can
be removed to fit a capture. Tune defaults after representative measurements.

Q21: Recommend supplied-file order/first appearance for tree siblings and
records initially, consistent with flat concatenation. Alternative timestamp
ordering needs missing/invalid timestamp rules.

Q22: Recommend a focused native Textual prototype after the user confirms the
complete design. Optional dependency; real-file paging/inspection, panes,
keyboard/mouse routes, representative tree/filter interactions, and cold/warm
opening/memory measurements at 1–5 GB. Validate actual local/SSH behavior.
Alternative is a complete implementation specification first.

Q19 decision: verify source contents before automatically reusing the cache.

Q20 decision: user reduced the proposed disk budget to 10 GB and allows a
higher RAM cache. Exact usage is unknown. Keep resource values provisional and
configurable; retain the proposed seven-day inactivity expiry. The 256 MiB RAM
cache is only a starting candidate for measurement, not a fixed requirement.

Q21 decision: preserve supplied-file order and first appearance for tree
siblings and records.

Q22 decision: a focused native Textual prototype to validate feasibility is
the next deliverable. Full production implementation is outside this step.

Final confirmation: user answered "yes" to the complete design summary.
