# IXR-only tooling migration specification

Status: implemented

Published to the local Markdown tracker on 2026-10-03. The design and public-query testing approach were approved in conversation. The breaking migration is implemented; delivery evidence is recorded in ticket 06 and the verification report. Standards/Spec code review is tracked separately.

## Problem Statement

slogger tooling currently has two expression routes: legacy predicates and filtering tools, and IXR query execution. Some objects retain both representations, and different execution adapters can consult different representations. Maintaining compatibility adds conversion, inspection, trust, cursor, replay, transport, and specialized-tool obligations to changes that should concern only query semantics.

The tooling implementation also mixes query planning, source handling, and backend execution in a flat collection of modules. This makes responsibilities difficult to locate and creates dependencies from adapters back into the execution coordinator for shared types.

Users want a small, coherent library for querying structured logs, with convenient expression construction, engine-independent semantics, and useful source handling. Downstream applications need to locate original records without tooling inserting synthetic fields into application data. The migration must remove obsolete code, tests, packaging, and documentation while leaving the core logging library unchanged.

## Solution

Make IXR the sole logical expression representation. Preserve convenient Field and boolean builders, but make them construct IXR directly. Execute immutable query plans through internal Python and optional Polars adapters, preserving the established typed query contract.

Organize tooling into query core, finite sources, and separate backend modules. Retain files, globs, stdin, finite record iterables, concatenation, and timestamp merging. Return source origin alongside each output record, independently of the application's fields.

Remove the entire legacy filtering route, specialized analysis tools, CLI, MCP, and their compatibility machinery. Replacement specialized tools and transports are future work. Update maintained documentation, examples, and benchmarks to describe only the retained architecture; clearly identify historical designs as superseded where they are retained.

## User Stories

1. As a library caller, I want convenient Field comparisons, so that readable queries do not require manual construction of expression trees.
2. As a library caller, I want boolean composition helpers, so that complex expressions remain easy to build.
3. As a library caller, I want builders to return IXR directly, so that expression meaning has one authoritative representation.
4. As a library caller, I want immutable expressions with snapshotted operands, so that later mutation cannot change my query.
5. As a library caller, I want missing fields to differ from present null, so that sparse logs remain accurately queryable.
6. As a library caller, I want booleans distinguished from numbers, so that typed comparisons do not conflate true with one.
7. As a library caller, I want explicit nested paths distinguished from literal dotted keys, so that field lookup is unambiguous.
8. As a library caller, I want scalar and array membership to remain distinct, so that collection queries have predictable meanings.
9. As a library caller, I want string, regex, and logger-prefix behavior preserved, so that migration does not silently weaken query semantics.
10. As a library caller, I want immutable query plans, so that extending a query does not modify its parent.
11. As a library caller, I want operation order to retain its meaning, so that limiting before filtering differs from filtering before limiting.
12. As a library caller, I want field projection, so that results contain only the application fields I select.
13. As a library caller, I want stable global sorting, so that equal-valued records have deterministic order.
14. As a library caller, I want grouping by multiple fields, so that logs can be summarized by meaningful dimensions.
15. As a library caller, I want named count, sum, mean, minimum, and maximum reductions, so that summaries are directly usable.
16. As a library caller, I want filters and sorts after aggregation, so that I can inspect computed group results.
17. As a library caller, I want invalid field dependencies rejected, so that queries cannot silently use fields removed by earlier operations.
18. As a library caller, I want explanation without reading input, so that inspection does not consume generators or stdin.
19. As a library caller, I want Python execution by default, so that ordinary tooling does not require a dataframe dependency.
20. As a library caller, I want explicit optional Polars execution, so that I can use native dataframe operations where supported.
21. As a library caller, I want explicit unsupported-operation and incompatible-data errors, so that execution does not silently fall back or coerce values.
22. As a library caller, I want identical supported query semantics across adapters, so that changing execution engines does not change results.
23. As a library caller, I want individual files and globs accepted, so that querying logs does not require manual discovery and decoding.
24. As a library caller, I want multiple files concatenated deterministically, so that source traversal is predictable.
25. As a library caller, I want ordered sources merged by timestamp, so that interleaved logs can be read chronologically.
26. As a library caller, I want finite stdin input accepted, so that redirected logs can be queried by library code.
27. As a library caller, I want in-memory records and generators accepted, so that applications and tests can query existing data.
28. As a library caller, I want construction and explanation to leave input untouched, so that one-shot sources remain available for execution.
29. As a library caller, I want lazy iterable ingestion, so that streamable plans can avoid exhausting an entire input unnecessarily.
30. As a library caller, I want malformed JSONL reported consistently, so that both adapters expose the same source diagnostics.
31. As a library caller, I want owned files closed on success, early termination, and failure, so that queries do not leak resources.
32. As a downstream application author, I want each record's original file and physical line number, so that I can open its source and surrounding lines.
33. As a downstream application author, I want iterable origins identified by input label and original position, so that I can locate records supplied by code.
34. As a downstream application author, I want origin preserved through filtering, projection, and sorting, so that result positions need not stand in for source locations.
35. As a downstream application author, I want origin separate from application fields, so that my own _id field remains ordinary data.
36. As a downstream application author, I want aggregate rows to have no single-record origin, so that summaries do not misleadingly point to one contributing line.
37. As a maintainer, I want adapters to consume the same IXR, so that custom callback behavior cannot disagree with declared expression meaning.
38. As a maintainer, I want shared runtime contracts owned outside the dispatcher, so that adapter dependencies have clear direction.
39. As a maintainer, I want legacy tools and their tests removed together, so that compatibility code cannot silently return.
40. As a maintainer, I want maintained docs and examples to reflect the new library, so that users do not copy removed interfaces.
41. As a maintainer, I want useful semantic tests retained at public interfaces, so that deleting old architecture does not delete protection for typed behavior.
42. As a logging user, I want core logging, schemas, context propagation, and compatibility imports unchanged, so that the tooling migration does not affect emission.
43. As a maintainer, I want end-to-end performance evidence, so that origin storage and dataframe conversion costs are visible without unsupported speed claims.

## Implementation Decisions

- This is a breaking tooling migration. No compatibility facade, forwarding import modules, or translation layer will preserve the retired filtering architecture. Core logging behavior and its public imports remain unchanged.
- The public tooling entry point remains slogger.tools. Export the retained query builders, plan/result types, origin contract, and tooling errors there; do not export tooling names from the logging package root.
- Organize implementation into core query, finite source, Python backend, and Polars backend ownership. Group related responsibilities rather than creating a module for every helper. Shared row, origin, and adapter contracts must not be owned by the dispatcher's implementation.
- IXR is the sole immutable expression representation. Field, all_of, any_of, not_, and logger-prefix conveniences construct IXR nodes directly. Remove the legacy Predicate abstraction, conversion methods, duplicate expression trees, cached facade matchers, custom executable predicate subclasses, and legacy inspection formats.
- Execution compilation belongs to adapters. Normalization and validation inspect IXR directly and no longer require checks of legacy facade identity or wrappers retained solely for old explanation. Existing IXR inspection can remain without becoming a JSON query-loading interface.
- Preserve supported expression semantics: typed equality, distinct missing/null, explicit literal and nested paths, snapshots of JSON operands, finite literal validation, string matching, boolean composition, scalar membership, and supported immediate-array membership. Do not introduce field-to-field comparisons or broader array traversal during this cleanup.
- QueryPlan retains scan, filter, select, sort_by, limit, group_by, aggregate, execute, and explain behavior. Grouped construction must be completed with aggregation before execution. Keep existing count_rows, sum_of, mean_of, min_of, and max_of helpers.
- Preserve operation order, schema lineage, stable ties, first-appearance group order, typed group identity, aggregate empty-input behavior, exact integer handling, and the corrected floating reduction contract. Initial projection, sorting, grouping, and reduction scope remains as currently implemented.
- Optimize only when meaning, diagnostics, and ordering remain valid. Filters cannot be pushed across limits indiscriminately; field availability must be respected. Delegate physical optimization to native adapters where the semantic contract permits it.
- Python remains the default adapter and Polars remains an explicit optional dependency. Both prepare validated IXR plans through an internal adapter interface. No public adapter registration, automatic engine selection, object UDF fallback, or silent cross-engine execution is added.
- Preserve existing explicit native capability limits and distinguish unsupported operations from incompatible data. Static explanation must identify checks that require data rather than claiming they have already succeeded.
- Retain deterministic path/glob expansion and rotation ordering, finite stdin, mapping iterables, concatenation, and k-way timestamp merging. Timestamp merge assumes each source is already ordered; it is distinct from a query's global sort. Preserve diagnostics for malformed records and problematic timestamps.
- Remove resume cursors, cursor parsing and eligibility metadata, incomplete live-input modes, repeated-pass replay/spooling, raw-line interfaces used only by retired tools, and field-cache sidecars. Reuse necessary parsing and ordering behavior without retaining the old public Reader contract.
- Plan construction and explanation do not open or consume sources. Source ingestion must not eagerly materialize generators for replay. Execution may materialize inputs when the adapter or operation requires it; global sort and aggregation need complete input. A zero limit must not consume records.
- Files and re-iterable inputs support repeated execution. Iterator and stdin inputs are one-shot; callers supply fresh input when another execution is needed. No hidden caching or replay guarantee is introduced. Capture iterable record contents when consumed so query operations do not mutate caller records.
- Finite source handling owns decoding, source accounting, and resource cleanup once for both adapters. Close owned file handles on failure and early termination. Do not close caller-owned stdin or iterator resources without an explicit ownership contract.
- Source origin is separate from application fields. A file origin identifies the concrete source and its one-based physical line number; skipped malformed lines do not renumber later origins. An iterable origin identifies its input label and original position with a documented base. Stdin receives a source label and line number.
- PlanResult retains records, schema, warnings, and execution metadata and gains an origin collection aligned by result index with records. Each entry describes that record's source origin or is absent for a derived summary row. Filtering, projection, and sorting preserve alignment; aggregation drops single-record origin. Document that these breaking result changes replace synthetic identity fields.
- An application's own _id is ordinary queryable data. Do not inject or reserve it for tooling identity; remove identity-specific projection/group/alias restrictions while retaining genuine output-name collision checks.
- Carry compact source references, physical positions, and stable ordinals internally. Source labels/path information can be shared rather than repeated as formatted strings. The public aligned-origin interface must allow compact or lazy internal storage; it does not mandate a Python wrapper allocation for every input row.
- Columnar execution must carry origin and stable-order lanes outside the user schema and reconstruct exact record shape. Preserve missing fields and nested data without introducing synthetic nulls or metadata fields.
- Remove legacy Filters/Where, query/Page/summary, trace/tree/span reconstruction, context selection, stats, failures, diff, field discovery/cache, validation/rendering helpers, tail/watch, and their transport-only helpers. Remove CLI, completion, module-entry dispatch to the CLI, MCP, transport output schemas, and transport-only dependency extras. Preserve the independent core log-record schema, core context/filter modules, and logging compatibility shims.
- Retain only necessary tooling errors and diagnostic information; remove cursor-specific and transport-only contracts. Errors should continue to identify the logical operation, field, and backend where available.
- Rewrite maintained API guidance, README, changelog, capability documentation, runnable examples, benchmark imports, and agent navigation guidance together. Remove obsolete transport documentation or clearly archive it as historical. Existing completed specifications remain historical evidence with prominent supersession notices; they cannot be cited as current compatibility requirements.

## Testing Decisions

- The approved primary testing interface is convenient builders plus QueryPlan.execute. Run the same logical queries and source cases through Python and actual Polars execution where supported.
- Good tests assert external results, application record shape, origin alignment, ordering, aggregate values, diagnostics, resource lifetime, and errors. They do not assert private compiler structure, facade cache identity, folder layout, or the number of branches in an implementation.
- Test static explanation through QueryPlan.explain and observe that sources remain untouched. Limited direct IXR construction/inspection tests are appropriate for its immutable logical contract, without recreating the retired predicate interface.
- Prior art is the existing query-plan, execution integration, typed-expression, source reader/merge, native sparse/array/string/sort/aggregate, optimizer, and optional-dependency coverage. Port useful cases to the retained public query interface before removing mixed legacy test files.
- Preserve missing/null, bool/number, large-number, nested/literal-key, immutable operand, regex, scalar/array, late-field/type, global sort/group, empty-input, and post-aggregation behavior coverage. Use meaningful adapter-parity cases, including cancellation-sensitive floating reductions, rather than implementation-mirroring tests.
- Test file, glob, multi-file, stdin, list, and one-shot generator inputs through queries. Verify lazy construction, explanation, zero-limit consumption, repeated execution for reusable sources, deterministic ordering, and owned-file cleanup on limits and errors. Do not claim all adapters stream every plan.
- Test actual physical origins after malformed lines, equal timestamps, filtering, projection, and sorting. Verify user _id fields are preserved normally. Test iterable input position and confirm aggregate origin entries are absent and remain aligned with summary output.
- Verify time merging of ordered sources and diagnostics for problematic timestamps. Do not incorrectly use timestamp merging as an oracle for globally sorting unsorted input.
- Remove tests of retired filters, custom callbacks, cursor/resume/replay, cache sidecars, specialized tools, CLI/completion, MCP, and transport schemas. Salvage independent typed/source semantics from mixed files; deleting filenames alone is insufficient.
- Keep core logging tests unchanged unless a nonbehavioral tooling reference requires cleanup. Run the full retained suite on Python 3.10 and 3.13 using editable installed packages, with optional Polars coverage and a base-install check without Polars. Run Ruff, Pyrefly, diff checks, and retained runnable documentation examples. CLI-help checks are retired with the CLI.
- Check installed public exports and optional imports for the retained library. Verify removed transport dependencies and schemas are absent from the built package while core typed markers and the log-record schema remain packaged.
- Audit maintained docs, examples, and benchmark entry points for removed imports and claims. Historical material must be explicitly superseded and not presented as current instructions.
- Run representative end-to-end benchmark comparisons including parsing, conversion, origin handling, execution, reconstruction, and memory where measurement is available. Preserve result-digest checks and identify the implementation/version measured. Do not require timing thresholds or advertise unmeasured speedups.

## Out of Scope

Changes to core logging, emitted record schemas, configuration, spans, instrumentation, context propagation, or root logging compatibility imports. Rebuilding CLI, TUI, MCP, trace/tree/context reconstruction, stats, diff, validation tools, or live watching. Public adapter plugins; pandas execution; automatic fallback; JSON/SQL query parsing; arbitrary executable predicates; new arithmetic, joins, window functions, computed projections, or multi-key sorting capabilities beyond the existing query contract. Persistent replay, source cursors, columnar caches, native file scanners, and aggregate contributor provenance. Automatic querying of source origin as a user field is not introduced; origin is exposed for downstream navigation.

## Further Notes

The accepted direction is recorded in [the IXR-only tooling ADR](../../docs/adr/0001-ixr-only-tooling.md), with terminology in [the glossary](../../GLOSSARY.md).

This specification supersedes the legacy-preservation requirements of [the completed IXR specification](../ixr-query-engine/spec.md) for this migration. Its implemented expression, query, and adapter semantics remain the starting point except where this specification explicitly changes representation, public exports, source identity, or retired capabilities. Removal of trace/tree tools withdraws reconstruction behavior; ordinary grouping is not a substitute for it.

The architecture report and approved conversation supplied the design; no prototype is needed to settle these decisions. Implementation tickets should be created separately as a blocker-aware graph, including semantic-test migration and documentation/package cleanup. This spec publication does not authorize silently skipping those delivery requirements.
