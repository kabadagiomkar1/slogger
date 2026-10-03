# 01: Separate shared runtime contracts and backend ownership

Status: ready-for-agent
Blocked by: none

**What to build:** Library callers can execute and explain existing query plans through Python and optional Polars while shared runtime contracts are owned by the query core and execution implementations live in separate backend modules. This is a behavior-preserving prefactor for the breaking migration described in the [specification](../spec.md).

- [ ] Shared execution row and adapter contracts are owned independently of the execution dispatcher's implementation; adapters do not import the dispatcher to obtain them.
- [ ] Python and Polars execution, compilation, sorting, reduction, and native binding responsibilities have clear backend ownership, with cohesive modules rather than forwarding compatibility files.
- [ ] The public tooling entry point, query construction, execution, explanation, diagnostics, and current source behavior remain usable during this prefactor.
- [ ] Python remains the default, Polars is imported only when selected, and no public adapter registry or silent fallback is introduced.
- [ ] Representative public-query tests pass on both adapters, including projection, stable sort, grouping, and aggregation. Static explanation leaves input untouched.
- [ ] Shared contracts permit source identity to move alongside records subsequently without making the dispatcher the owner of source semantics.
- [ ] Navigation and architecture guidance affected by the ownership change is updated. Core logging behavior and its compatibility imports are unchanged.

## Implementation guidance

Use the established public-query tests as the primary verification interface. Keep this ticket focused on ownership and dependency direction; do not introduce the new origin return contract or delete the predicate representation here. Avoid speculative abstractions beyond the two existing adapters.

Ticket 02 has no technical dependency on this prefactor. If both are implemented concurrently, coordinate public-import changes before integrating them.
