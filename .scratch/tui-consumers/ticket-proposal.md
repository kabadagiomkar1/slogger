# Approved production TUI breakdown

Approved on 2026-10-04: the user replied "ok" to the proposed granularity
and blocking edges. Published 19 individual production tickets, all marked
ready-for-agent. Their individual files are authoritative for lifecycle state.

Initial ready frontier: **06**. Implementation has not started.

## Published tickets

| Ticket | Blocked by |
| --- | --- |
| [06: Open supplied logs in a stable native split view](issues/06-native-stable-split-view.md) | none |
| [07: Browse progressive capture and recover from opening failures](issues/07-progressive-capture.md) | 06 |
| [08: Read long console messages comfortably](issues/08-console-navigation.md) | 06 |
| [09: Inspect and compare complete JSON records](issues/09-json-inspector.md) | 06 |
| [10: Apply the complete IXR filter language](issues/10-ixr-filters.md) | 06 |
| [11: Complete filter syntax while editing](issues/11-filter-syntax-completion.md) | 10 |
| [12: Discover keys and values across the whole dataset](issues/12-field-value-completion.md) | 11 |
| [13: Search filtered records with live highlighting](issues/13-record-search.md) | 10 |
| [14: Explore complete cross-file trace trees](issues/14-trace-trees.md) | 06 |
| [15: Filter and search through ancestor context](issues/15-filtered-tree-context.md) | 13, 14 |
| [16: Count values where the selected field exists](issues/16-field-presence-counts.md) | 09, 10 |
| [17: Summarize numeric fields exactly](issues/17-numeric-summaries.md) | 16 |
| [18: Group summaries by multiple and nested fields](issues/18-grouped-summaries.md) | 17 |
| [19: Detach and reattach aggregate filters with completion](issues/19-independent-aggregate-filters.md) | 12, 16 |
| [20: Reopen verified datasets and reclaim cache safely](issues/20-verified-cache-lifecycle.md) | 06 |
| [21: Save useful global preferences and themes](issues/21-global-preferences.md) | 08, 09, 20 |
| [22: Refresh without losing the latest investigation state](issues/22-atomic-refresh.md) | 07, 15, 18, 19, 21 |
| [23: Validate and harden real terminal and SSH interactions](issues/23-terminal-ssh-validation.md) | 22 |
| [24: Qualify 1–5 GB investigations and choose resource defaults](issues/24-scale-qualification.md) | 22 |

Source: [accepted production specification](spec.md), including shared tooling
clarifications at integration baseline **7de401a**.

Keep resolved prototype tickets 01–05 unchanged. Continue the same effort with
production tickets **06–24**, in dependency order. All proposed slices include
their investigation-operation tests, focused native tests where applicable,
appropriate compatibility checks, and current documentation/changelog updates.
Tests exercise installed packages and real JSONL sources. Shared operations are
headless, accept explicit scopes, and preserve IXR semantics and source origins.
No CLI/MCP transport implementation is added.

No standalone framework or wide mechanical prefactoring ticket is required.
Necessary shared-source factoring precedes capture changes within 06; bounded
delivery is introduced through filtered browsing in 10; grouping and reductions
are introduced through the exact aggregate workflows in 16–18. Preserve existing
finite-source operations and materialized QueryPlan execution throughout.

## Approved slices

### 06: Open supplied logs in a stable native split view

**Blocked by:** none.

**What it delivers:** An optional installed terminal application opens supplied
files into a stable disk-captured dataset, pages the console stream in input
order, and shows the selected record's complete JSON in a narrower right pane.

- Ordered and repeated input occurrences, opening byte boundaries, and source
  physical lines survive capture and paging. Later appends do not alter the
  captured investigation. No synthetic application metadata is injected.
  A shared completeness/readiness contract guards dataset-wide operations.
- Shared decoding handles malformed/non-object lines and valid final objects
  without newlines; diagnostics and original source locations remain accurate.
- Console defaults recognize real slogger timestamp/level/logger/message/span,
  hide known metadata, show user fields, and align message starts. Generic objects
  and real Unicode remain readable; demonstration messages use ASCII.
- Keyboard paging/selection and basic mouse selection synchronize the JSON
  inspector. Complete admitted records are available, with syntax colors and
  parsed-record indication rather than a fixed text preview cap.
- Capture, paging, record admission, and disk/RAM working storage have explicit
  resource contracts and clean close behavior. The basic resource-accounting
  mechanism exists from the first storage-producing operation; later slices
  account for their own indexes/results through it.
- Headless open/page/close operations work without Textual. Base logging/IXR
  imports create no files/handlers and optional dependency failures are useful.
- Initial opening is demoable after capture completes; 07 adds progressive
  browsing and its full interaction/failure policy.

### 07: Browse progressive capture and recover from opening failures

**Blocked by:** 06.

**What it delivers:** A large investigation becomes browseable during capture,
with honest progress, safe cancellation, and retained partial records on failure.

- Background capture permits console selection and JSON inspection of the
  captured prefix; the shared readiness contract keeps all dataset-wide
  operations unavailable until complete, including operations added by other slices.
- Failed/canceled opening retains already captured records until session close,
  marked incomplete, with actionable diagnostics and no reusable-complete flag.
- Observed source truncation/replacement/mutation, file access failures, disk
  exhaustion, and declared oversized-record limits cannot silently omit data.
- Closing/canceling releases owned resources and superseded capture work cannot
  publish into a newer investigation.

### 08: Read long console messages comfortably

**Blocked by:** 06.

**What it delivers:** Console navigation remains useful with long messages,
wide custom fields, narrow terminals, and real variable-height wrapping.

- Wrap/pan controls preserve complete content and record selection; no fixed
  three-line or character preview limit replaces the original message.
- Vertical/horizontal keyboard routes and available mouse scrolling work
  alongside paging, with stable aligned columns and narrow-layout focus routes.
- Session controls expose time-only, date-and-time, original timestamp, and
  optional duration display. Full original field values remain inspectable.
- Rendering/cache memory stays bounded under the declared admitted-record
  envelope, including resize and repeated navigation.

### 09: Inspect and compare complete JSON records

**Blocked by:** 06.

**What it delivers:** The right pane is independently navigable, resizeable,
toggleable, and pinnable, with complete record inspection and usable key targets.

- Navigate long prettified JSON vertically/horizontally without a character
  preview cap; expose optional line numbers and retain valid-record indication.
- Hide/resize and pin/unpin have keyboard equivalents; selection and pinned
  inspection are distinct and source identity is visible.
- JSON key navigation exposes unambiguous nested/literal field targets for later
  field actions. Copy uses supported terminal capabilities or reports that it
  is unavailable; copied content is complete.
- Narrow resize and focus changes do not strand controls or discard a pin.

### 10: Apply the complete IXR filter language

**Blocked by:** 06.

**What it delivers:** An approachable infix editor produces exact paged filtered
views through shared IXR execution, with responsive, cancelable application.

- Comparisons, structural equality, membership, array operators, substring,
  regex, starts_with, presence/missing, logger_prefix, parentheses, and boolean
  precedence retain the full current reference semantics.
- Nested and quoted literal-key paths, typed values, missing/null, and
  bool/number distinctions resolve without coercion or application-field aliases.
- Complete result delivery preserves origins and order with bounded working
  memory; existing QueryPlan execution remains compatible.
- Draft, applied, and pending state is clear. Enter applies; useful syntax/type
  errors, Esc cancellation, and stale completions preserve the successful view.
- Python is the reference default; optional native execution is only exposed
  explicitly with its existing capability/dependency errors and no fallback.

### 11: Complete filter syntax while editing

**Blocked by:** 10.

**What it delivers:** Contextual syntax choices help build a valid filter through
operators, functions, connectors, parentheses, and appropriately typed operands.

- Keyboard up/down/Tab, mouse acceptance, dismissal, and continued editing work
  without overwriting a newer draft or prefix.
- Completion respects parsed context and supplies useful repair guidance.
  The editor interaction is reusable by the later independent aggregate editor.
- This slice completes syntax; 12 adds whole-dataset keys and observed values.

### 12: Discover keys and values across the whole dataset

**Blocked by:** 11.

**What it delivers:** The same completion menu discovers every observed field
and scalar value, including rare late trace/span names and identifiers.

- Disk-backed discovery covers the complete investigation without sampling
  caps on lines, keys, or values. Progress/readiness is explicit.
- Small prefix-matched pages, common-value ranking without a prefix, and
  narrowed prefixes make all observed scalar choices reachable.
- Typed values and nested/literal paths insert with correct escaping. Stale
  discovery jobs cannot replace choices for a later dataset or prefix.
- Discovery/result storage participates in disk accounting and keeps working
  memory bounded for high-cardinality data.

### 13: Search filtered records with live highlighting

**Blocked by:** 10.

**What it delivers:** Literal text search highlights as the user types and
navigates matching records inside the applied Main filter without filtering them.

- Console/full-record scopes use complete decoded names/values, including
  hidden metadata in full scope; serialization escapes do not become matches.
- Case and Unicode whole-word options, immediate highlights, no typing-driven
  cursor movement, complete background record counts, and next/previous/wrap
  navigation are usable with clear option states.
- Changing scope, case, word options, or console-field visibility recomputes
  visible highlights and the complete match set, superseding prior work.
- Empty search clears matches. Filter/request changes invalidate stale match
  scopes; cancellation and pending status preserve the prior successful view.
- The complete match index is paged/disk-backed and resource-accounted.

### 14: Explore complete cross-file trace trees

**Blocked by:** 06.

**What it delivers:** The complete captured dataset can be explored as a paged,
foldable trace/span tree with honest lifecycle and relationship evidence.

- Trace ID and trace-plus-span ID provide identity; names are labels. Roots,
  siblings, and records preserve file order and first appearance.
- Single/all fold controls, left/right navigation, mouse actions, and flat/tree
  switching preserve selected record identity where possible.
- Untraced records, missing parents, incomplete/conflicting spans, and cycles
  retain all source evidence without inventing duration or trustworthy parents.
- Reconstruction/indexing is background, disk-backed, resource-accounted, and
  complete beyond the former preview cap. Canonical lifecycle events are used.
- This slice demos the unfiltered tree; 15 adds the filtered/search cross-view
  behavior. Unsupported interim combinations are indicated rather than misleading.

### 15: Filter and search through ancestor context

**Blocked by:** 13, 14.

**What it delivers:** Tree mode honors the applied filter while retaining marked
ancestors, and search reveals matching records through folded paths.

- Ancestor context explains matches but is not itself a filter/search match or
  aggregate contributor merely because it is displayed.
- Search next/previous reveals required ancestors and keeps source-order
  navigation and flat/tree selection coherent.
- Filter/search generation changes cannot publish stale tree membership or
  context; uncertainty remains honestly represented.

### 16: Count values where the selected field exists

**Blocked by:** 09, 10.

**What it delivers:** Selecting a console/JSON field or a keyboard field target
opens exact categorical counts in a lower pane following the Main filter.

- The visible span label selects its canonical span field; console and JSON
  targets resolve the same field paths regardless of display spelling.
- Compose selected-field presence into the explicit operation scope before
  count/grouping or resource admission. Missing is excluded; null/zero/false
  remain present. The public row-count primitive retains its existing meaning.
- Typed scalar grouping, first-appearance order, repeated record occurrences,
  empty results, and collection/type errors preserve IXR semantics.
- Selected nested paths and literal keys use collision-safe out-of-band binding
  for value counts. This slice introduces that single-path capability; 18
  extends/reuses it for multiple grouping fields.
- Count the complete scope and page high-cardinality groups without preview
  caps, synthetic fields, or fabricated aggregate origins.
- Main-filter changes produce correctly scoped background jobs; pending/failed
  results retain their old scope label and stale jobs cannot publish.
- Bounded count/group storage participates in the shared resource contract.

### 17: Summarize numeric fields exactly

**Blocked by:** 16.

**What it delivers:** Selecting a numeric field returns count, sum, mean,
minimum, and maximum for the complete present-field scope.

- Numeric null behavior, incompatible false/non-numeric/nonfinite values,
  empty scopes, exact large integers, and compensated floating reductions
  agree with the reference. Count includes present null rows as specified.
- Bounded/spill reduction avoids naive batch-sum or batch-mean shortcuts;
  cancellation, errors, and cleanup preserve the last successful pane.
- Nested numeric paths and literal keys work without injecting application
  fields. Metric selection is editable and errors give useful type guidance.

### 18: Group summaries by multiple and nested fields

**Blocked by:** 17.

**What it delivers:** The aggregate editor adds multiple grouping fields and
metrics, with exact paged summaries over nested or literal-key fields.

- Extend/reuse collision-safe shared path binding while preserving literal top-level
  grouping compatibility and does not rewrite source application records.
- Secondary grouping keys preserve missing/null and typed numeric/bool rules;
  only the selected aggregate field receives the automatic presence guard.
- High-cardinality groups preserve first appearance and complete reductions
  with bounded working memory, disk admission, progress, and cancellation.

### 19: Detach and reattach aggregate filters with completion

**Blocked by:** 12, 16.

**What it delivers:** An aggregate can copy the currently applied Main filter
into an independent editor, refine it with full completion, and explicitly reattach.

- Both editors share syntax, key/value discovery, typed insertion, keyboard,
  and mouse interaction. Detachment copies applied rather than draft text.
- Detached scopes survive subsequent main changes without changing the main
  view; reattachment resumes following the latest applied Main filter.
- Scope generations, selected-field presence, retained-result labels, errors,
  and cancellation work consistently for all available aggregate metrics.
- Numeric/grouped metrics and detachment can evolve concurrently through the
  same explicit operation scope; dependencies do not impose a false sequence.

### 20: Reopen verified datasets and reclaim cache safely

**Blocked by:** 06.

**What it delivers:** Reopening verifies source contents before reusing completed
capture/index data, and resource controls reclaim only safe unused storage.

- Verify current boundaries, ordered/repeated inputs, content changes even
  with unchanged size/mtime, versions, and corruption. A saved prefix followed
  by appends cannot count as the current complete dataset.
- Choose durable cache location/versioning and protect active datasets across
  processes. Recover stale ownership and clean expired/abandoned captures.
- Account for allocated capture/index/result/staging/journal/spill storage;
  expose usage, configurable budget/expiry, and protected clear controls.
- Default to provisional 10 GB managed disk and seven-day inactivity expiry;
  resource failures stay actionable. RAM browsing limits are configurable and
  distinct from total process memory. 24 selects a measured default.
- Verification/reuse progress is visible; cache reuse does not imply zero I/O.

### 21: Save useful global preferences and themes

**Blocked by:** 08, 09, 20.

**What it delivers:** A keyboard-accessible settings view changes real presentation
and resource behavior, with coherent dark/light themes and explicit saved defaults.

- Theme, wrap, timestamp, duration, inspector line numbers, pane size/visibility,
  resource limits, expiry, usage, and protected clearing are usable options.
- Session adjustments do not implicitly overwrite global defaults; saving is
  explicit. Query/search/navigation histories remain session-only.
- Narrow layouts preserve access and both themes provide readable control,
  JSON, selection, error, and search-highlight states.

### 22: Refresh without losing the latest investigation state

**Blocked by:** 07, 15, 18, 19, 21.

**What it delivers:** Explicit refresh captures separately while the old
investigation stays usable, then publishes a coherent replacement atomically.

- Reconcile main/independent filters, search/options, tree state, panes,
  preferences, and aggregate configuration edited during replacement capture.
  Reapply the latest active scopes before publication; no unfiltered flash.
- Restore selection/pins only for verified identical source occurrences;
  changed, disappeared, or ambiguous identities produce explicit diagnostics.
- Failed/canceled or over-budget refresh keeps the old complete dataset and
  result handles usable. Active plus replacement storage remains accounted.
- Controlled interleavings demonstrate stale old jobs cannot publish into the
  new dataset, and unsuccessful staging is safely cleaned.

### 23: Validate and harden real terminal and SSH interactions

**Blocked by:** 22.

**What it delivers:** The complete workflow has documented actual local/remote
terminal support and targeted fixes for reported interaction failures.

- Exercise supported local terminals and SSH/multiplexer sessions for resize,
  mouse scrolling/panning, selection, paste/copy, focus/tab switching, and all
  keyboard fallbacks. Retain the reported Codex mouse case as unreproduced
  unless new evidence establishes a cause.
- Declare the tested platform/dependency/capability matrix and useful unavailable
  diagnostics. Headless or PTY checks are not substitutes for emulator/SSH evidence.
- No credentials, SSH host provisioning, or access permissions are assumed.
  Provide a reproducible manual exercise; if required environments are unavailable,
  record that validation as pending rather than claim it passed or silently close
  the requirement. Coordinate environment-dependent evidence with the user.
- Public installation/use guidance reflects the actual optional package setup
  and distribution naming constraints, with no identical-appearance claim.

### 24: Qualify 1–5 GB investigations and choose resource defaults

**Blocked by:** 22.

**What it delivers:** Reproducible measurements establish the production resource
envelope and RAM default for complete 1 GB and 5 GB investigations.

- Representative 100–200 MB files include custom/sparse/nested fields, long
  messages, cross-file traces, and high-cardinality groups. Record revision,
  input identity, machine, and cold/warm OS-cache conditions.
- Measure first browseable/complete opening, verified reuse cost, filters,
  search, completion, trees, aggregates, idle/active CPU, peak RSS, and total/
  peak disk including refresh staging. Account for failures under 10 GB honestly.
- Verify bounded working memory beyond browsing-cache admission; select and
  document a practical RAM default and admitted-record/resource envelope.
- Existing prototype timings are historical. No invented latency/CPU guarantees
  or sampled results replace required correctness. Correctness regressions are
  addressed in their owning slices rather than hidden behind qualification.
- Terminal validation and scale qualification can run concurrently; neither
  is a semantic prerequisite for the other's independent evidence.

## Review and execution notes

- Initially 06 is the production frontier. After 06, capture interactions,
  console comfort, inspector controls, cache, filters, and traces can proceed
  independently. Shared readiness keeps global operations honest when progressive
  capture is introduced; it does not require unrelated features to wait for 07.
- Blocking edges describe behavior needed by the slice, not shared-file overlap.
  Before concurrent implementation, add coordination to overlapping tickets for
  shared module ownership, operation contracts, UI integration, and test/import
  reconciliation as the local workflow requires.
- Verify editable environments against the implementation checkout before
  dispatch. Keep each completed slice green; preserve Python 3.10/3.13 endpoint
  and optional-dependency contracts where affected.
- Scope review: 06–09 cover opening and inspection; 10–13 cover filter/completion/
  search; 14–15 cover trees; 16–19 cover aggregates; 20–21 cover cache/settings;
  22 covers transactional refresh; 23–24 cover external terminal and scale evidence.
- The required granularity and dependency review is complete. The user approved
  publication; one ready-for-agent file now exists per production ticket. This
  document retains the approved breakdown and indexes the individual tracker files.
