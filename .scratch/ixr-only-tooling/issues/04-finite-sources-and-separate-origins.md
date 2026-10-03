# 04: Provide finite sources with separate origins

Status: resolved
Blocked by: 01, 02

**What to build:** Callers query finite files, globs, stdin, and record iterables without unnecessary eager consumption, and downstream applications can locate output records through origin information alongside application data. Deliver source ingestion and origin propagation through both adapters end to end, following the [specification](../spec.md).

- [x] The source module owns JSONL decoding, deterministic path/glob/rotation expansion, concatenation, timestamp merging, diagnostics, and owned-resource cleanup for both adapters.
- [x] Preserve useful file, stdin, sequence, and finite iterable inputs. Timestamp merge interleaves already ordered sources and reports existing problematic-timestamp diagnostics; it does not claim to globally sort unsorted inputs.
- [x] Plan construction and explanation do not open or consume inputs. Generator ingestion is lazy rather than materialized for replay; zero-limit execution consumes no records.
- [x] Document which operations/adapters require materialization. File and re-iterable plans can execute again; stdin and iterators remain one-shot unless fresh input is supplied.
- [x] Remove resume cursors, cursor parsing/eligibility metadata, live incomplete-input modes, replay/spooling, and obsolete raw-line/source helper contracts. Do not retain the old public Reader interface through a shim.
- [x] File origins use concrete source identity and one-based physical line numbers, including gaps from malformed lines. Stdin origins use a source label and line number; iterable origins use a label and original position with a documented index base.
- [x] PlanResult exposes an origin collection aligned with its records. Filtering, projection, and sorting preserve that alignment; each aggregate summary row has an absent single-record origin.
- [x] User records receive no synthetic identity field. A logged _id remains ordinary data and is selectable, filterable, sortable, and groupable where its values meet the existing operation contract.
- [x] Remove identity-specific reserved-name restrictions while preserving genuine grouping-key and aggregate-output collisions.
- [x] Preserve stable ordering and exact record reconstruction across both adapters using internal origin/order lanes outside the application schema.
- [x] Internal storage uses shared source references and compact positions where practical; origin separation does not require repeated path strings or one wrapper per input row.
- [x] Public-query tests cover malformed lines, equal timestamps, mixed sources, projection/sort/filter origin preservation, aggregate origin absence, user _id fields, lazy generators, repeated reusable input, and unchanged caller records.
- [x] Owned files close on success, early termination, and errors. Caller-owned stdin/iterator resources are not closed without an explicit ownership contract.
- [x] Update source/result examples and guidance to show the breaking origin contract and accurate consumption/ownership behavior.

## Implementation guidance

Use the shared runtime contracts established by ticket 01; legacy source consumers are retired by ticket 02. Origin is for downstream navigation, not a newly introduced query field. Aggregate contributor provenance and persistent replay remain out of scope.

Coordinate shared plan/result and adapter edits with ticket 03 during integration. Their independent behavior can be verified through public query calls without imposing an artificial dependency between them.

## Resolution

Finite Sources now owns decoding, deterministic discovery, rotation ordering,
concatenation, timestamp merge diagnostics, and owned file lifetime. Iterables
are consumed lazily and copied at consumption. Removed the Reader facade,
cursors/errors/eligibility, replay, live and raw-line contracts.

SourceOrigin(source, position, kind) is exported with aligned PlanResult.origins.
File/stdin positions are one-based physical lines; mem/mem1 iterable positions
are zero-based. Existing runtime rows share source-label strings and carry
original positions and stable ordinals. Projection/filter/sort preserve origins;
aggregates have None. User _id is ordinary application data. Both execution
adapters preserve exact shapes and ordering. Strict zero limits skip source reads
even before blocking operations, retain static validation, and preserve
subsequent summaries of empty input.

Validation on Python 3.13.9 / Polars 1.44.2 after integrating ticket 03:
319 retained tests passed, including 16 new adapter-parametrized source/origin
cases. Ruff passed, Pyrefly reported zero errors, and diff checks passed.
Updated API origin/consumption examples and implementation ownership guidance.
Cross-version packaging and benchmark evidence are handled by tickets 05/06.
