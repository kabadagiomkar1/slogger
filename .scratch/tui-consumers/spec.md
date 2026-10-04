# Native IXR investigation TUI

Status: ready-for-agent

Type: specification

This specifies production implementation of the accepted native design. The
resolved prototype tickets establish design evidence; they do not implement
this specification. Implementation tickets have not yet been created.

## Problem Statement

A developer investigating structured logs needs to move between a readable
console stream, the complete JSON record, related spans, and field summaries.
Reading JSONL directly obscures the message and useful context; repeatedly
running separate queries makes navigation and comparisons cumbersome.

The investigation commonly contains 1–5 GB across files of approximately
100–200 MB each. Loading all decoded records and query results into RAM is
unsuitable. Reopening the same files should avoid unnecessary reconstruction,
while protecting against stale cache contents and unbounded disk consumption.
Records must stay stable during an investigation, including when the original
files continue growing.

The accepted native prototype demonstrates the desired interaction and visual
direction. Its sampling, preview caps, storage accounting, and materialized
query execution cannot become production correctness or resource guarantees.
The developer needs a terminal application that uses IXR semantics faithfully
and remains useful locally and through SSH, with clear terminal capability
limits and keyboard alternatives.

## Solution

Build an optional Textual TUI around one stable Investigation dataset. Opening
supplied finite JSONL files presents their records in supplied-file order,
with progressive browsing while capture continues. A compact Console view is
paired with a narrower, toggleable JSON inspector on the right. Field
aggregates open below the stream. Flat and trace/span tree modes share the
selected record, main filter, search, and source awareness.

The developer edits an approachable infix Main filter with contextual syntax,
key, and typed-value completion. Record search navigates within the applied
filter and highlights matches as text is entered. Selecting a field starts an
exact aggregate over records where that field exists, following the Main
filter by default or using an independently editable scope.

Capture data, indexes, and complete operation results in bounded disk storage;
use a configurable RAM cache for browsing and bounded working memory for
execution. Reuse completed captures only after verifying source contents.
Refresh explicitly and publish a successful replacement atomically. Keep the
last successful investigation usable during pending work or a failed refresh.

Global preferences control presentation and resource budgets. Keyboard
navigation covers every mouse interaction. The native terminal interface is
the product; the earlier web prototype remains historical design evidence.

## User Stories

1. As a developer, I want to open an ordered set of finite JSONL files, so that I can investigate several services or runs together.
2. As a developer, I want the initial stream to concatenate files in the supplied order and preserve records within each file, so that navigation follows the inputs I chose.
3. As a developer, I want subtle file demarcation and the selected record's source origin, so that I can distinguish files without cluttering every message.
4. As a developer, I want physical source-line numbers distinct from displayed record positions, so that skipped input lines do not make locations misleading.
5. As a developer, I want to browse captured records before loading finishes, so that a large investigation becomes useful progressively.
6. As a developer, I want incomplete capture and unavailable global operations clearly indicated, so that partial data cannot be mistaken for the complete investigation.
7. As a developer, I want the dataset to remain stable until I explicitly refresh, so that changing source files cannot alter results underneath my cursor.
8. As a developer, I want later appends included only after refresh, so that a session has a clear source boundary.
9. As a developer, I want actionable capture errors and decoding diagnostics, so that I can understand missing input and recover.
10. As a developer, I want a failed refresh to preserve the previous complete dataset, so that a transient failure does not destroy my investigation.
11. As a developer, I want successful refresh to preserve filters, search, panes, and aggregate configuration, so that I can continue the same investigation with new data.
12. As a developer, I want selection and pins restored only for verified identical records, so that refresh does not silently point me at a different event.
13. As a developer, I want a console row containing timestamp, level, logger, message, span name, and custom fields, so that useful information is readable at a glance.
14. As a developer, I want metadata such as attribution and trace identifiers hidden by default, so that the main stream stays compact while inspection remains complete.
15. As a developer, I want message starts aligned within each tree depth, so that scanning several records is comfortable.
16. As a developer, I want time-only, date-and-time, and original timestamp display modes, so that I can read either a short incident or a multi-day investigation.
17. As a developer, I want optional duration display, so that I can surface timing when it helps without adding it to every default row.
18. As a developer, I want vertical navigation, paging, jump-to-start/end, and horizontal panning, so that I can explore long and wide logs with a keyboard.
19. As a developer, I want wrapping to be a preference that preserves full content, so that narrow terminals remain useful.
20. As a developer, I want mouse selection and scrolling when my terminal reports them, so that local navigation feels direct.
21. As a developer, I want a keyboard route for every mouse operation, so that the application remains usable remotely and in limited terminals.
22. As a developer, I want a narrower right inspector showing the selected record's complete prettified JSON with syntax colors, so that I can inspect context alongside the stream.
23. As a developer, I want to hide or resize the inspector, so that I can reclaim horizontal space for messages.
24. As a developer, I want to pin an inspected record while moving through the stream, so that I can compare nearby events with a reference.
25. As a developer, I want to copy record content through an available terminal capability, so that I can reuse evidence outside the application.
26. As a developer, I want JSON navigation, optional line numbers, and a clear parsed-record indicator, so that long records remain inspectable without editing them.
27. As a developer, I want real slogger logs and their custom fields displayed correctly, so that the application works with emitted data rather than only its demo.
28. As a developer, I want a compact Main filter editor with an infix language, so that I can express IXR predicates without assembling Python objects.
29. As a developer, I want all existing IXR filter capabilities available, so that the approachable interface does not reduce the backend's expressive power.
30. As a developer, I want nested paths and literal keys containing dots or spaces to be distinguishable, so that I can target the intended field precisely.
31. As a developer, I want typed values and missing-versus-null behavior preserved, so that filters mean the same thing in the TUI and IXR.
32. As a developer, I want syntax, operator, function, and connector completion, so that I can construct valid filters without memorizing every spelling.
33. As a developer, I want key and value completion across the complete dataset, including trace and span identifiers, so that rare late records are discoverable.
34. As a developer, I want completion choices selectable by keyboard or mouse, so that suggestions speed up editing without interrupting it.
35. As a developer, I want draft, pending, and applied filters visibly distinguished, so that I know which expression produced the current view.
36. As a developer, I want invalid or canceled filter changes to retain the successful view, so that experimentation does not discard useful results.
37. As a developer, I want search to navigate records rather than filter them, so that I can find text while retaining surrounding context.
38. As a developer, I want search scoped to either console fields or the complete record, so that I can choose readable content or hidden metadata.
39. As a developer, I want console-field search to use full field names and values despite display truncation, so that invisible portions of a long message are still findable.
40. As a developer, I want explicit case-sensitive and whole-word search options, so that I can control literal text matching.
41. As a developer, I want live highlighting while typing without automatic cursor movement, so that I can refine a search in place.
42. As a developer, I want match counts and next/previous navigation relative to the cursor with wrapping, so that I can traverse every matching record.
43. As a developer, I want search to honor the applied Main filter, so that its matches belong to the view I am investigating.
44. As a developer, I want a matching record revealed through folded ancestors, so that tree navigation does not hide search results.
45. As a developer, I want flat and tree views to retain the same selected record when possible, so that changing representation does not lose my place.
46. As a developer, I want traces joined across all supplied files by trace ID and spans identified within a trace, so that shared span names do not merge unrelated work.
47. As a developer, I want tree siblings and records ordered by file order and first appearance, so that tree navigation is consistent with the console stream.
48. As a developer, I want single-node and whole-tree fold/unfold actions with keyboard navigation, so that I can move between an overview and detailed events.
49. As a developer, I want filtered trees to retain clearly marked ancestor context, so that matching events still have an understandable hierarchy.
50. As a developer, I want untraced records, missing parents, incomplete spans, and conflicting relationships represented honestly, so that damaged or partial traces remain investigable.
51. As a developer, I want every source record retained independently of tree summaries, so that reconstruction never erases evidence.
52. As a developer, I want to select a field from either the console or JSON inspector to open an aggregate pane, so that summaries are close to the records that prompted them.
53. As a developer, I want categorical value counts and numeric count, sum, mean, minimum, and maximum defaults, so that useful summaries require little setup.
54. As a developer, I want to edit the aggregate field, grouping, and metrics, so that I can refine a summary without leaving the investigation.
55. As a developer, I want aggregates to follow the Main filter by default, so that a summary describes the records currently under investigation.
56. As a developer, I want to detach an aggregate by copying the current filter and editing its own scope, so that I can compare a separate population.
57. As a developer, I want the independent aggregate filter to have the same syntax and completion support as the Main filter, so that detached scopes remain easy to edit.
58. As a developer, I want to reattach an aggregate to the Main filter explicitly, so that its scope can follow subsequent investigation changes again.
59. As a developer, I want aggregate counts and reductions to exclude records where the selected field is missing, so that summaries describe actual field occurrences.
60. As a developer, I want explicit null, zero, false, and incompatible numeric values handled according to IXR, so that summary values are trustworthy.
61. As a developer, I want exact aggregates over the complete scope with paged group results, so that preview caps do not masquerade as complete answers.
62. As a developer, I want scopes and pending aggregate results clearly labeled, so that an old summary cannot appear to describe a newly applied filter.
63. As a developer, I want queries, searches, completion, trees, and aggregates to run in the background, so that browsing remains responsive.
64. As a developer, I want to cancel or supersede work safely, so that stale results cannot overwrite a newer request.
65. As a developer, I want completed captures reused after source-content verification, so that reopening avoids redundant decoding and indexing without trusting stale data.
66. As a developer, I want configurable disk and RAM cache budgets with visible usage, so that investigations fit my machine's resources.
67. As a developer, I want expired and abandoned cache data cleaned up while active datasets are protected, so that storage remains bounded across sessions.
68. As a developer, I want a clear-cache action that respects active investigations, so that reclaiming space does not corrupt work.
69. As a developer, I want global presentation defaults and temporary session adjustments, so that the application suits my terminal without persisting investigation history.
70. As a developer, I want coherent dark and light themes, readable search colors, and useful settings controls, so that the interface remains comfortable in different environments.
71. As a developer, I want narrow terminal layouts and focus changes to preserve essential actions, so that resizing and remote use do not make controls inaccessible.
72. As a developer, I want an optional terminal installation and clear launch diagnostics, so that core logging and query tooling remain usable without the TUI dependency.
73. As a developer, I want actual terminal and SSH behavior validated and limitations documented, so that I know which interactions my environment supports.
74. As a maintainer, I want investigation operations tested with real JSONL inputs and focused native interaction tests, so that correctness is verified independently of widget internals.
75. As a maintainer, I want repeatable scale measurements that distinguish cold capture from verified reuse, so that resource and performance claims have inspectable evidence.

## Implementation Decisions

1. **Consumer and ownership boundaries.** Build a production Textual consumer
   and a tooling-owned Investigation session. The TUI owns layout, focus,
   input, and rendering. Investigation tooling owns dataset capture, cache
   lifecycle, paging, search indexes, completion, trace reconstruction, and
   operation coordination. IXR and its execution adapters continue to own
   predicate evaluation, typed grouping, and reductions. Share these semantics
   rather than implementing another predicate engine in a storage language.
   Keep the investigation module headless and independent of Textual so future
   CLI and MCP consumers can call the same operations. Shared tooling owns
   reusable filter parsing/path resolution and discovery; the TUI owns editor
   interaction and human workflow defaults. CLI/MCP may use finite IXR
   operations directly or opt into captured datasets without adopting the
   TUI's session workflow. Bounded execution improvements belong to shared
   tooling, not to terminal widgets.

2. **One investigation interface.** The session exposes opening/capture,
   progress and diagnostics, paged record access with origins, query/filter
   execution with explicit scopes, Record search, completion, tree navigation,
   field aggregates, refresh, cancellation, and close. Operations return structured scopes,
   status, result handles, and diagnostics rather than rendered strings.
   Keep widgets thin and make this the primary consumer testing boundary.
   Reuse existing source and IXR seams underneath it; do not revive removed
   legacy Reader, cursor, trace, cache, CLI, or MCP contracts.
   Main/detached filter relationships, editor drafts, selection/pins, display
   folding, panes, key bindings, and presentation preferences belong to the
   TUI consumer; shared operations receive explicit input/dataset/view scopes,
   IXR expressions, and execution options. Structured callers need not use the
   infix editor language. Some operations require dataset or result handles
   and temporary storage; a shared capability need not be stateless. Results
   carry application data, origins, and diagnostics
   independently of terminal markup or Textual/Rich types. Future transport
   adapters define JSON encoding, wire schemas, and external handle lifetimes;
   this spec does not implement those transports or make local result/job
   handles a JSON wire contract. Consumer-specific aggregate defaults compose
   shared primitives without changing their meaning.

3. **Installed package and optional dependencies.** Keep production code in
   the installable src layout. Provide an optional TUI dependency extra and
   an installed launch entry point accepting ordered finite JSONL inputs.
   Textual is not required to import core logging or Python IXR. Logging
   exports remain in slogger.__all__; public tooling exports belong to
   slogger.tools.__all__. Neither import creates files, captures data, or
   attaches handlers. Preserve compatibility imports and the formators alias.
   Declare and verify supported terminal/platform dependencies; base logging
   remains independent of TUI platform choices.

4. **Capture boundary and source identity.** Establish a byte boundary for
   every supplied regular file when opening the investigation. Capture only
   records within those boundaries; append activity beyond them waits for
   explicit refresh. Decode with the shared source rules, retaining the
   physical source line and input occurrence independently of user fields.
   Detect truncation, replacement, or observed mutation of the captured
   portion and report capture failure rather than publish an unverified
   snapshot. This is an application capture boundary, not a claim of an
   operating-system snapshot for concurrently rewritten files.

5. **Record identity and origins.** Dataset record identity, query-result
   position, input occurrence, and Source origin are separate concepts.
   Repeated supplied files retain repeated record occurrences. Preserve
   original file/physical-line origins through bounded execution and paging;
   iterable batches must not replace them with batch-local positions.
   Application keys such as _id or names resembling internal fields remain
   untouched. Derived aggregate rows have no fabricated source origin.

6. **Progressive opening and failures.** Console browsing and JSON inspection
   operate on the captured prefix with an explicit loading/incomplete state.
   Dataset-wide filters, search, completion, trees, and aggregates become
   available only when capture and their required indexes are complete.
   Malformed JSON and non-object lines follow shared skip/diagnostic rules;
   skipped physical lines still affect origins. Accept a valid final JSON
   object without a trailing newline; malformed partial final JSON follows
   normal shared decoding rules. Failed initial capture retains already
   captured records for session browsing/inspection with an explicit
   incomplete/error state and global operations disabled. Canceling initial
   capture likewise retains that prefix until the session is closed. Neither
   prefix produces complete-dataset results or becomes a reusable completed
   cache. Report file access, decoding, disk, and resource errors actionably.

7. **Disk dataset and bounded execution.** Retain captured records and indexes
   on disk with a process-local configurable RAM browsing cache. Bound
   execution working memory as well as display caching: current QueryPlan
   execution materializes PlanResult records, and current reductions can
   retain all contributions. Add a tooling-owned paged/spill execution and
   reduction path for the investigation while preserving existing execute
   behavior and IXR semantics. Complete filtering, search, completion, tree
   reconstruction, and aggregates must not load the full decoded dataset or
   all high-cardinality results into RAM.

8. **Exact results and numeric compatibility.** Disk/batch processing is a
   delivery strategy, not a new query meaning. Preserve reference operation
   ordering, typed equality, missing/null handling, exact integer behavior,
   compensated floating reductions, empty-input results, and documented
   errors. Combining batch sums or averages naively is not equivalent to
   existing reductions. Design and verify bounded reduction strategies
   against the reference, including cancellation and cleanup. Resource
   exhaustion produces an explicit failure; samples and truncated results
   must never be labeled complete or exact.

9. **Large records.** Replace fixed preview limits with virtualized or paged
   rendering and inspectable complete content. Bound record admission and
   per-operation working memory through a documented strategy. If a record
   cannot be handled within a declared resource limit, surface a diagnostic
   and explicit incomplete/failure state; do not silently adopt the demo's
   oversized-record skip policy. No claim is made that an arbitrarily large
   individual JSON value fits a fixed RAM budget.

10. **Reusable cache verification.** Persist completed captures across launches.
    Cache identity includes ordered input occurrences and relevant capture,
    schema, and index versions. Verify source contents, including the captured
    bytes, before automatic reuse; size and modification time alone are
    insufficient. Match every input occurrence's current opening byte boundary
    as well as its content. An unchanged cached prefix plus later appends is
    not the complete dataset for a new open or refresh. Whole-file content
    hashing is an acceptable starting strategy. Reuse may avoid copying,
    decoding, and indexing, but verifying
    the files still costs I/O and cannot be advertised as an instantaneous
    open. Reject stale, incompatible, corrupt, or unverified entries safely.

11. **Cache budget and lifecycle.** Start with a provisional configurable
    10 GB total managed disk budget and configurable inactivity expiry,
    initially seven days. Account for captured data, allocated index/database
    space, operation results,
    staging, journals, and temporary/spill work. Protect active datasets with
    process-safe leases or locks, recover stale ownership safely, and clean
    expired or abandoned work. Show actual managed usage and a clear-cache
    action that respects active datasets. A 5 GB active capture plus its
    replacement and indexes can exceed 10 GB; reject or cancel that work
    actionably while retaining the active dataset. Choose a durable cache
    location, versioning, and cross-process accounting contract explicitly.

12. **RAM budget.** Expose a configurable browsing cache budget. Its exact
    default is chosen from production measurements; 256 MiB is an initial
    candidate, and the demo's 32 MiB was only a validation setting. These
    values are neither total-process RSS limits nor measured scale
    guarantees. Measure widget/index/job working memory independently and
    keep it bounded relative to configured resources and maximum admitted
    record size.

13. **Refresh transaction.** Capture a replacement separately while the last
    complete dataset and its views remain usable. Retain Main and independent
    filters, search/options, panes, aggregate configuration, and preferences.
    Reconcile filters, settings, and requests changed during capture and reapply
    the latest active state before atomically publishing the replacement;
    never briefly expose an unfiltered replacement as the filtered view.
    Failed or canceled refresh preserves the old dataset. Restore selection
    and pins only where source identity and record content verify the same
    occurrence. Report changed, disappeared, or ambiguous records explicitly
    and select a documented fallback rather than guessing by a user field.

14. **Background jobs and scopes.** All scans and index building run outside
    the UI event loop. Each job and result belongs to a dataset generation,
    applied query scope, and request generation. Superseding or canceling
    work prevents stale publication and releases its resources. Retain the
    last successful view during pending or failed work; label its applied
    scope and progress accurately. Esc cancels pending work without
    discarding that view. Main, detached aggregate, completion, and refresh
    jobs follow the same rule. A retained aggregate must show its own old
    scope while a replacement is pending.

15. **Console layout.** Use the accepted split-inspector layout: broad main
    stream, narrower toggleable right JSON inspector, and aggregate pane
    below the stream. Provide compact labeled filter/search rows, clear mode
    and option states, and restrained controls. Display timestamp, level,
    logger, message, a bracketed span label when present, then user fields.
    Hide attribution, trace/span/parent IDs, events, and duration by default;
    duration is a preference. Keep the accepted source/record index treatment
    with subtle source demarcation. Pad timestamp, level, and a stable capped
    logger column so message starts align at each tree depth. Full values
    remain available despite column ellipsis or horizontal clipping.

16. **Real schema compatibility.** Canonical slogger records use span for the
    span label, span.start/span.end for lifecycle events, and file/func/line
    for attribution. Use these without changing the emitted schema. An
    external span_name label can be tolerated as a presentation fallback,
    with canonical span taking precedence. Recognize known metadata and
    exception/stack content separately from user fields, including the
    prototype's external metadata aliases where supported. The JSON
    inspector always retains the original record. Generic JSON objects with
    absent console fields remain browseable using honest fallbacks; strict
    slogger schema validation is not a requirement for ingesting every object.

17. **Navigation and inspector.** Support up/down, page movement, home/end,
    horizontal panning, record selection, and practical mouse scroll/click
    routes. Wrapping uses the real content length and variable row height,
    retaining record selection across wrapped lines. The inspector renders
    complete read-only prettified JSON with syntax colors, optional line
    numbers, parsed-record indication, independent scrolling, hide/resize,
    pin/unpin, and copy. Choose an available clipboard route or show a clear
    unavailable state. Virtualization must replace the demo's fixed line and
    character preview caps. Every action has a discoverable keyboard route.

18. **Filter language.** Translate approachable infix predicates into IXR
    expression nodes. Cover current comparisons, membership and negated
    membership, immediate-array contains_any/contains_all, literal substring
    contains, regex matches, generic starts_with, exists, missing, and
    logger_prefix. Support parentheses and NOT before AND before OR.
    Operands preserve JSON types and supported structural equality; do not
    coerce strings, numbers, booleans, null, or missing into each other.
    Preserve backend semantics and errors for each operator. This is a full
    filter editor, not a general query-plan authoring or sorting interface.

19. **Field paths and editing.** Dots represent nested traversal; quoted
    bracket components represent exact keys, including keys containing dots,
    spaces, quotes, and mixed nested/literal paths. Completion inserts the
    unambiguous spelling and typed JSON value with correct escaping. Apply
    a Main filter on Enter; keep draft text distinct from the applied
    expression and pending request. Syntax errors include useful location
    and repair guidance without replacing the prior successful view.

20. **Completion index and interaction.** Use the whole captured dataset,
    including rare keys and scalar values near its end, for key/value
    discovery. Include syntax, connectors, operators, functions, trace IDs,
    span IDs, and span/trace names where supplied. Show small prefix-matched
    lists and prefer common values without a prefix; narrowed prefixes must
    make every observed scalar value reachable. Disk-backed indexes and
    paged choices are allowed; fixed sampling/value caps are not a claim of
    complete discovery. Main and independent aggregate filters share this
    language and contextual completion. Support up/down, acceptance with
    Tab or a click, dismissal, and continued editing without stale choices
    replacing a later prefix.

21. **Backend selection.** Python remains the reference default. The TUI must
    support the complete current IXR filter domain through its reference
    path. Optional Polars execution, if exposed, is explicit and respects
    its existing unsupported, data_incompatible, dependency, regex, and
    precision contracts. No automatic switch or silent fallback changes
    meaning. Public adapter registration is not part of this work.

22. **Record search.** Search is literal text navigation over records admitted
    by the applied Main filter. Console scope examines complete names and
    values of the fields included in the Console view, despite ellipsis,
    wrapping, or timestamp formatting. Full-record scope examines all names
    and values, including hidden metadata and exceptions. Expose case
    sensitivity and whole-word matching; the accepted whole-word option is
    not regex matching or whole-field equality. Search decoded field names
    and string values; use consistent JSON scalar representations for other
    values without treating serialization escape artifacts as text. Define
    word boundaries consistently for Unicode and test them. Typing updates
    visible highlights immediately without moving the cursor, while a debounced
    cancellable background job computes the complete record match set and
    count. Empty search clears matches. Enter/next/previous navigate relative
    to the cursor, wrap, and reveal folded ancestors. Count matching records
    separately from text occurrences. A changed filter invalidates the old
    match scope until the new search result is ready.

23. **Tree reconstruction and ordering.** Build disk-backed, lazily paged
    traces across all captured files. Trace ID joins traces; trace ID plus
    span ID identifies a span; names are labels, never identity. Preserve
    supplied-file order and first appearance for trace roots, sibling spans,
    and records rather than sorting by timestamps. Keep untraced and
    insufficiently identified records accessible. Switch flat/tree views
    using stable record identity where possible. Fold/unfold individual nodes
    and the whole tree; provide click/space actions and left/right navigation
    for collapse/parent and expand/child. Do not retain the demo's first-record
    tree preview or bounded ancestor enrichment as production limits.

24. **Ancestor context and uncertain traces.** Filtered trees retain the
    ancestors needed to explain matching records, visibly marked as Ancestor
    context. Context is not a filter match and contributes neither search
    matches nor aggregate rows merely because it is displayed. Use explicit
    placeholders for missing parents and clear states for incomplete or
    conflicting spans. Detect cycles and contradictory parent/lifecycle
    evidence without implying a reliable hierarchy. Preserve all original
    records and summarize only unambiguous observed evidence. Recognize
    canonical slogger lifecycle events; absent end/start evidence is not
    proof of completion or duration. No inferred trace-duration metric or
    implicit span deduplication is introduced.

25. **Field aggregates and scope.** Selecting a console field or JSON key,
    including a span label through its canonical field, opens the lower pane
    with an editable selected field, grouping, and metrics. Categorical scalar
    fields default to value counts; numeric fields offer count, sum, mean,
    min, and max. Follow the applied Main filter by default. Detaching copies
    that applied expression into an independent editor; later main changes
    do not affect it. Reattaching explicitly resumes following. Nested fields
    are selectable. Mixed, collection, or incompatible domains produce
    useful type guidance rather than coercion or silent record removal.

26. **Selected-field presence.** Aggregate input is the chosen main or
    independent scope intersected with exists(selected field), before counts,
    grouping, reductions, or any resource admission limit. Missing selected
    fields contribute nothing. Explicit null is present and contributes to
    row count and categorical null groups; numeric reductions retain IXR's
    null behavior. Zero and false are present; false is not a numeric value.
    Other grouping fields retain existing missing/null group semantics.
    Preserve count_rows as a count of all upstream rows: add the presence
    guard in this consumer query, not in the public count primitive. Count
    record occurrences, including repeated input occurrences, without
    implicitly deduplicating spans or traces.

27. **Grouping and result delivery.** Preserve scalar-only grouping domains,
    bool/number distinction, compatible numeric grouping, missing/null
    distinction, and first-appearance group ordering. The current public
    grouping interface binds literal top-level keys; nested grouping requires
    a tooling-owned path-binding extension or an out-of-band collision-safe
    binding, without synthetic fields injected into application records.
    Numeric nested paths already follow IXR field semantics. Aggregate
    results cover the entire exact scope and page arbitrary group counts;
    remove the demo's eligible-record, byte, and displayed-group preview caps.

28. **Preferences.** Persist global defaults for dark/light theme, wrapping,
    timestamp mode, optional duration, inspector line numbers, pane
    visibility/width, and resource budgets. Expose cache usage and protected
    clearing. Apply temporary session changes without implicitly saving them;
    provide an explicit save-defaults action. Keep query, search, and
    navigation histories in the current session initially. Settings must be
    usable with a keyboard and in narrow layouts, with readable option state
    and both themes verified. ASCII-only demo messages are a fixture choice;
    real Unicode input remains supported.

29. **Terminal behavior.** Validate actual supported local terminals and SSH
    sessions, including resize, focus/tab switching, mouse reporting, and
    multiplexer behavior. Terminal-reported horizontal gestures and clipboard
    integration may vary; keyboard equivalents preserve functionality.
    Document the tested capability/platform matrix and failure diagnostics.
    Do not promise identical fonts, colors, gestures, network latency, or
    lower CPU than a web UI without evidence. The reported Codex tab-switch
    mouse problem remains a validation case, not an established root cause.

30. **Implementation completion.** Update current user documentation,
    architecture/capability documentation where contracts expand, the domain
    glossary where new public terms are needed, and the changelog for public
    behavior. Retain the accepted ADRs and existing logging/schema contracts.
    Keep the prototype as evidence rather than importing its storage and
    execution shortcuts wholesale. Record release/install instructions that
    reflect the project's package naming constraints.

## Testing Decisions

1. **Approved primary seam.** The user explicitly approved real JSONL inputs
   exercised through Investigation session operations, plus focused native
   TUI tests. Most tests open temporary files and drive the same capture,
   paging, filters, search, completion, tree, aggregate, refresh, cancellation,
   and close operations used by Textual. Assert returned records, source
   origins, scope/status, ordering, diagnostics, and visible state. Avoid
   coupling tests to storage tables, private widget methods, or reducer
   implementation details.

2. **Existing semantic authority.** Reuse IXR integration, origin, predicate,
   aggregation, and optional-dependency test patterns. Compare investigation
   execution with the Python reference on seeded sparse/nested typed data,
   literal dotted keys, structural comparisons, arrays, presence/null, and
   supported string predicates. Add focused tooling-level tests only where
   new bounded delivery, path binding, or reduction behavior needs a contract
   beyond the session boundary. Preserve current public execution behavior.

3. **Capture and provenance.** Test multiple real files, duplicate inputs,
   blank/malformed/non-object lines, physical line numbers after skips,
   application keys resembling internal metadata, ordinary Unicode input,
   and actual records emitted by slogger with canonical span/lifecycle and
   attribution fields. Check progressive browse/inspection, retained prefixes
   after initial failure/cancellation, global-operation gating, empty files,
   valid final records without newlines, malformed partial final records,
   later appends, observed truncation/replacement/mutation, close cleanup,
   and declared large-record
   resource behavior. No silent prototype-only skip or truncation rule passes.

4. **Cache lifecycle.** With real temporary cache directories, test verified
   reuse, changed contents with unchanged size/mtime, incompatible versions,
   damaged entries, ordered inputs, and changed opening boundaries after
   appends. Verify total disk accounting and admission including indexes,
   staging, temporary job data,
   and database allocation where applicable. Test expiry, abandoned captures,
   stale ownership recovery, competing-process active leases, protected clear,
   disk-full/resource failures, and active-dataset survival. Do not mock away
   every filesystem operation in these contract tests.

5. **Refresh and generations.** Verify settings and independent scopes survive
   successful refresh, prior complete data survives failed/canceled refresh,
   and the replacement is published only after the latest active state is
   applied, including filters/settings changed while capture was running.
   Test verified selection/pin restoration and changed/disappeared/ambiguous
   identity diagnostics. Use controllable scheduling and failure injection
   to finish an old request after a new one and assert it cannot publish.
   Avoid timing-sensitive sleeps as the definition of correctness.

6. **Search and completion.** Verify console/full-record scopes, untruncated
   values and names, metadata/exceptions, decoded quotes/backslashes/newlines,
   case and whole-word behavior, no cursor movement from typing, match count
   versus occurrence count,
   next/previous/wrap, folded-ancestor revelation, and filter-generation
   invalidation. Place rare fields/IDs after all former sampling boundaries
   and verify prefix discovery with typed insertion and escaped literal
   paths. Main and independent aggregate editors exercise the same language.

7. **Tree behavior.** Test cross-file traces, identical names and span IDs in
   different traces, source-order versus timestamp-order disagreement,
   filtered ancestor context, untraced records, missing parents, incomplete
   lifecycle evidence, contradictory parents, and cycles. Verify complete
   coverage beyond former preview caps, conservative summaries, folding and
   selection continuity, and that context does not inflate search/aggregate
   populations.

8. **Aggregates and bounded execution.** Test selected-field absence versus
   null/zero/false, main/detached/reattached scopes, nested and literal keys,
   grouping with missing/null secondary keys, mixed/incompatible domains,
   empty scopes, repeated occurrences, and more groups than a display page.
   Exercise spill/batch boundaries with exact large integers, cancellation,
   and floating values that expose naive sum-of-sums or average-of-averages
   errors. Compare results and failures with the reference semantics; test
   complete scopes beyond the demo's record/byte caps. Measure bounded
   working memory separately from browsing-cache admission.

9. **Focused native suite.** Use a small Textual headless interaction suite
   for keyboard/mouse selection, focus routes, console alignment and wrapping,
   inspector toggling/pinning, flat/tree folding, contextual completion in
   both editors, live highlight and option states, aggregate scope controls,
   preferences, narrow/wide resize, and readable dark/light themes. Use
   structured state assertions and a few purposeful visual snapshots rather
   than brittle screenshots of every widget or mirroring rendering code.

10. **Dependency and compatibility checks.** Test installed packages, including
    a fresh interpreter where optional Textual and Polars are unavailable.
    Logging and Python IXR imports remain usable with no handlers or files
    created; headless Investigation session operations work without Textual.
    TUI launch reports a useful missing-dependency message. Validate
    Python 3.10 and 3.13 endpoints and the declared TUI dependency/platform
    range. Preserve schema, compatibility imports, and exports. Run repository
    formatting, typing, integration, and documentation checks appropriate to
    production changes; do not introduce unrelated CI work.

11. **Real terminal checks.** Perform local terminal and SSH validation with
    the supported capability matrix, including Ghostty, Codex's embedded
    terminal where available, and a supported multiplexer. Check mouse events
    after tab/focus changes, scroll/pan, paste, clipboard, resize, keyboard
    fallbacks, and remote navigation latency. Record unavailable combinations
    or unreproduced issues honestly. Headless tests and PTY smoke tests cannot
    alone establish actual emulator gestures, appearance, or SSH behavior.

12. **Scale evidence.** Measure production cold capture and verified reuse
    at 1 GB and 5 GB with representative 100–200 MB files, realistic custom
    fields, sparse/nested values, long messages, traces, and high-cardinality
    groups. Record source/code identity, machine and OS-cache conditions,
    first browseable time, complete capture/index time, verification cost,
    query/search/tree/aggregate latency, idle and active CPU, peak RSS, and
    total/peak disk including refresh staging. Report failures under the
    provisional 10 GB budget instead of weakening exactness. Select and
    document the production RAM default and practical resource envelope from
    these measurements. Quantitative latency/CPU thresholds have not been
    approved; do not convert old demo timings into production acceptance
    guarantees. Rerun relevant measurements when the execution strategy changes.

## Out of Scope

- The automation consumer's CLI/MCP primitives, JSON transport, and structured
  query loading. A launcher for the native TUI is in scope.
- Live tail/watch/follow mode, stdin streams, and automatic refresh. Inputs
  are supplied finite regular files and refresh is explicit.
- A web interface or productionizing the earlier web prototype.
- A general query-plan authoring UI for projection, sorting, arbitrary
  operation pipelines, or every compounded workflow. This interface exposes
  the full current IXR filter domain and the specified aggregate workflow.
- Approximate/sample aggregate results presented as the normal complete
  workflow; search top-word suggestions and persistent investigation history.
- Changes to core logging, emitted log schema, compatibility shims, or the
  project's public distribution name. The unrelated PyPI slogger package
  cannot be assumed to install this project.
- Public adapter registration, automatic Polars selection, or silent fallback.
- Processor pipelines, OTel expansion, sequence tools, framework middleware,
  and CI changes.
- Importing the throwaway prototype wholesale as production architecture or
  treating its preview caps and synthetic schema as public contracts.

## Further Notes

- The user accepted the refined native direction and requested the transition
  to actual implementation. The latest reviewed prototype source baseline is
  **286197e**, including selected-field presence for aggregates. This is
  design approval, not evidence that production requirements are implemented.
- The testing boundary was explicitly confirmed: **investigation operations
  plus focused native TUI tests**. No further design interview is required to
  create implementation tickets from this specification.
- Accepted decisions are recorded in the
  [design interview](design-interview.md), the
  [IXR ownership ADR](../../docs/adr/0001-ixr-only-tooling.md), and the
  [stable dataset ADR](../../docs/adr/0002-stable-tui-investigation-datasets.md).
  Use the [domain glossary](../../GLOSSARY.md),
  [tooling architecture](../../docs/tools-architecture.md),
  [execution capability contract](../../docs/execution-compatibility.md), and
  [logging contracts](../../docs/agents/logging-contracts.md) as semantic
  authorities. Extend current documentation when new contracts are implemented.
- Design evidence and review fixes are captured in the resolved
  [visual prototype](issues/01-visual-prototype.md),
  [native feasibility prototype](issues/02-native-prototype.md),
  [interaction refinement](issues/03-native-interaction-refinement.md),
  [alignment and completion response](issues/04-native-review-response.md),
  and [aggregate presence correction](issues/05-aggregate-field-presence.md).
  The [native guide](../../examples/prototypes/NATIVE.md) explains how to
  inspect that evidence. Production must replace its sampled completion,
  tree/aggregate previews, fixed wrapping/text caps, weak refresh restoration,
  and incomplete disk accounting.
- Existing [native measurements](../../examples/prototypes/native-measurements.md)
  belong to **1b202f7**, synthetic regular JSON, warm OS cache, and single local
  macOS runs. Later visual and aggregate refinements were not remeasured at
  1–5 GB. They establish feasibility evidence with those limits, not production
  startup, total-memory, disk, CPU, or exact-result guarantees.
- The user observed normal mouse behavior in Ghostty and an issue after tab
  switching in Codex's terminal. The issue is unreproduced and unattributed;
  retain it as a manual validation case. No evidence yet establishes identical
  appearance/behavior across remote terminals or a CPU advantage over a web UI.
- Test prior art includes
  [execution integration](../../tests/test_tools_execution_integration.py),
  [source origins](../../tests/test_tools_origins.py),
  [query plans](../../tests/test_tools_plans.py),
  [predicate integration](../../tests/test_tools_predicate_integration.py),
  [reference aggregation](../../tests/test_tools_plan_aggregation.py),
  [Polars aggregation](../../tests/test_tools_polars_aggregation.py), and
  [optional dependency isolation](../../tests/test_tools_polars_dependency.py).
  There is no existing production Textual test suite to preserve.
- Implementation choices still to record are the physical bounded/spill
  execution strategy, durable cache location and lease/accounting details,
  supported platform/dependency matrix, precise trace-evidence rules,
  large-record admission limits, and measured RAM default. These are bounded
  implementation tasks under this contract, not unresolved user preferences.
- Publishing here follows the [local Markdown tracker](../../docs/agents/issue-tracker.md).
  The next workflow step is **/to-tickets** to split this ready specification
  into implementation work. Existing numbered issues are resolved prototype
  work; production tickets must distinguish their purpose and dependencies.
