# 01: Separate shared runtime contracts and backend ownership

Status: resolved
Blocked by: none

**What to build:** Library callers can execute and explain existing query plans through Python and optional Polars while shared runtime contracts are owned by the query core and execution implementations live in separate backend modules. This is a behavior-preserving prefactor for the breaking migration described in the [specification](../spec.md).

- [x] Shared execution row and adapter contracts are owned independently of the execution dispatcher's implementation; adapters do not import the dispatcher to obtain them.
- [x] Python and Polars execution, compilation, sorting, reduction, and native binding responsibilities have clear backend ownership, with cohesive modules rather than forwarding compatibility files.
- [x] The public tooling entry point, query construction, execution, explanation, diagnostics, and current source behavior remain usable during this prefactor.
- [x] Python remains the default, Polars is imported only when selected, and no public adapter registry or silent fallback is introduced.
- [x] Representative public-query tests pass on both adapters, including projection, stable sort, grouping, and aggregation. Static explanation leaves input untouched.
- [x] Shared contracts permit source identity to move alongside records subsequently without making the dispatcher the owner of source semantics.
- [x] Navigation and architecture guidance affected by the ownership change is updated. Core logging behavior and its compatibility imports are unchanged.

## Implementation guidance

Use the established public-query tests as the primary verification interface. Keep this ticket focused on ownership and dependency direction; do not introduce the new origin return contract or delete the predicate representation here. Avoid speculative abstractions beyond the two existing adapters.

Ticket 02 has no technical dependency on this prefactor. If both are implemented concurrently, coordinate public-import changes before integrating them.

## Resolution

Moved reference execution/compilation/sorting/reductions into the Python backend
and native execution/binding/sorting/reductions into the Polars backend. Shared
execution row/result and adapter/source protocols now belong to the query core;
adapters no longer import the dispatcher. Reader lifecycle remains in the
coordinator until source migration. Shared projection and field lookup belong to
core. No forwarding modules or public registry were added. Updated implementation
navigation, including the coordinated legacy retirement described by ticket 02.

Validation: existing public-query characterization suite passed before and after
(124 tests). Full editable-installed Python 3.13.9 / Polars 1.44.2 suite: 507 passed.
Ruff and Pyrefly checks passed. This behavior-preserving prefactor relies on the
approved existing query tests rather than adding folder-structure assertions.
