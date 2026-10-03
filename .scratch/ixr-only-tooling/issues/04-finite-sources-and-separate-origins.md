# 04: Provide finite sources with separate origins

Status: ready-for-agent
Blocked by: 01, 02

**What to build:** Callers query finite files, globs, stdin, and record iterables without unnecessary eager consumption, and downstream applications can locate output records through origin information alongside application data. Deliver source ingestion and origin propagation through both adapters end to end, following the [specification](../spec.md).

- [ ] The source module owns JSONL decoding, deterministic path/glob/rotation expansion, concatenation, timestamp merging, diagnostics, and owned-resource cleanup for both adapters.
- [ ] Preserve useful file, stdin, sequence, and finite iterable inputs. Timestamp merge interleaves already ordered sources and reports existing problematic-timestamp diagnostics; it does not claim to globally sort unsorted inputs.
- [ ] Plan construction and explanation do not open or consume inputs. Generator ingestion is lazy rather than materialized for replay; zero-limit execution consumes no records.
- [ ] Document which operations/adapters require materialization. File and re-iterable plans can execute again; stdin and iterators remain one-shot unless fresh input is supplied.
- [ ] Remove resume cursors, cursor parsing/eligibility metadata, live incomplete-input modes, replay/spooling, and obsolete raw-line/source helper contracts. Do not retain the old public Reader interface through a shim.
- [ ] File origins use concrete source identity and one-based physical line numbers, including gaps from malformed lines. Stdin origins use a source label and line number; iterable origins use a label and original position with a documented index base.
- [ ] PlanResult exposes an origin collection aligned with its records. Filtering, projection, and sorting preserve that alignment; each aggregate summary row has an absent single-record origin.
- [ ] User records receive no synthetic identity field. A logged _id remains ordinary data and is selectable, filterable, sortable, and groupable where its values meet the existing operation contract.
- [ ] Remove identity-specific reserved-name restrictions while preserving genuine grouping-key and aggregate-output collisions.
- [ ] Preserve stable ordering and exact record reconstruction across both adapters using internal origin/order lanes outside the application schema.
- [ ] Internal storage uses shared source references and compact positions where practical; origin separation does not require repeated path strings or one wrapper per input row.
- [ ] Public-query tests cover malformed lines, equal timestamps, mixed sources, projection/sort/filter origin preservation, aggregate origin absence, user _id fields, lazy generators, repeated reusable input, and unchanged caller records.
- [ ] Owned files close on success, early termination, and errors. Caller-owned stdin/iterator resources are not closed without an explicit ownership contract.
- [ ] Update source/result examples and guidance to show the breaking origin contract and accurate consumption/ownership behavior.

## Implementation guidance

Use the shared runtime contracts established by ticket 01; legacy source consumers are retired by ticket 02. Origin is for downstream navigation, not a newly introduced query field. Aggregate contributor provenance and persistent replay remain out of scope.

Coordinate shared plan/result and adapter edits with ticket 03 during integration. Their independent behavior can be verified through public query calls without imposing an artificial dependency between them.
