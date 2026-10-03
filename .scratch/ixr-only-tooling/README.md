# IXR-only tooling migration

The [specification](spec.md) and this six-ticket breakdown were approved in conversation. Each ticket is independently claimable only when all its blockers are resolved. All six implementation tickets are resolved. Delivery verification is recorded in [ticket 06](issues/06-integrate-and-verify-migration.md) and the [verification report](../../docs/reviews/ixr-only-verification.md). Standards/Spec code review is complete; see [the review report](../../docs/reviews/ixr-only-review.md).

| Ticket | Blocked by | Delivery |
| --- | --- | --- |
| [01: Runtime contracts and backend ownership](issues/01-runtime-contracts-and-backend-ownership.md) | none | Behavior-preserving execution prefactor |
| [02: Remove legacy tools and transports](issues/02-remove-legacy-tools-and-transports.md) | none | Retired interfaces, dependencies, tests, and instructions removed |
| [03: Direct IXR builders and query core](issues/03-direct-ixr-builders-and-query-core.md) | 01, 02 | One expression representation across both adapters |
| [04: Finite sources and separate origins](issues/04-finite-sources-and-separate-origins.md) | 01, 02 | Lazy finite ingestion and origins alongside results |
| [05: Documentation, examples, and benchmarks](issues/05-documentation-examples-and-benchmarks.md) | 03, 04 | Complete reconciliation against final contracts |
| [06: Integrate and verify](issues/06-integrate-and-verify-migration.md) | 05 | Verified package, semantics, docs, and measurements |

The completed graph began with 01 and 02; their resolution enabled 03 and 04. Those two tickets can proceed independently, but edits to public exports, plan/result contracts, shared rows, and adapter integration must be coordinated. Prefer one integration branch for the migration; no temporary compatibility form may remain at completion.

Claim a ticket by setting its Status to claimed. Record changes and validation under its Resolution section, then set Status to resolved. Work blockers-first; do not infer completion from a ticket's triage status.
