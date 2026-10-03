# IXR-only tooling final code review

Review date: 2026-10-03. Fixed point: `e97419b`. Reviewed integration HEAD:
`4fa6ede` on `codex/ixr-only-tooling`, using the three-dot diff and its 18 commits.
The review covered the authoritative specification, all six tickets, glossary,
accepted ADR, source and query ownership, retained adapters and semantic tests,
public exports, package metadata, and unchanged logging behavior.

## Standards

Zero hard violations; zero actionable baseline smell findings. The installable
source layout and tooling-only exports follow the documented standards. Shared
runtime contracts, finite sources, and adapters have coherent ownership. Direct
builders remove the middle-man Predicate facade and duplicate expression state.
The internal adapter interface has two actual implementations.

Origins remain separate from application fields and survive projection and
sorting; aggregate rows have no single-record origin. Owned file streams close
on success, limits, and errors, while caller-owned stdin and iterables remain
open. Public query tests cover these behaviors. Independent core regression
assertions were retained when obsolete tooling assertions were removed.

Maintained guidance, examples, historical supersession notices, transport removal,
and packaging are consistent with the migration. Backend visitors differ by
responsibility and capability, and do not warrant a forced shared execution
abstraction. This axis was read-only and did not independently rerun tests.

## Spec

One original actionable finding, P3: the historical IXR specification's opening
notice simultaneously described the migration as implemented and not yet
implemented. This contradicted the requirement for accurate historical
supersession guidance. The notice is corrected to identify the completed
IXR-only migration while preserving the historical baseline below it.

No other missing, incorrect, or expanded-scope requirements were identified.
Both adapters consume the same immutable IXR; validation precedes source
consumption and native capability failures remain explicit. Deferred ingestion,
zero-limit behavior, ownership cleanup, physical line origins, iterable positions,
alignment through record operations, absent aggregate origins, ordinary
application _id fields, stable ordering, and typed/native semantics match the
approved contract. Core logging implementation and schemas remain unchanged;
the package-root change is documentation only.

Per-input origin objects are a permitted representation choice, not an
unmeasured optimization guarantee. No public adapter registry, fallback,
replacement transport, or new query operations were introduced.

## Validation and resolution

The Spec reviewer ran 102 targeted tests with installed Python 3.13 / Polars
1.44.2, covering origins, time merge, expressions, normalization, native sparse
and array behavior, and plans. Public integer-mean probes around 2**53 and the
Int64 maximum matched both adapters.

[Delivery verification](ixr-only-verification.md) separately records full
319-test suites at Python 3.10 and 3.13, base and wheel checks, static checks,
examples, and end-to-end benchmark evidence. The single review correction is
documentation-only; it does not require new behavioral tests or benchmark runs.
Its diff and local Markdown links were checked.

Final outcome: zero unresolved Standards findings; zero unresolved Spec
findings. All six implementation tickets remain resolved.
