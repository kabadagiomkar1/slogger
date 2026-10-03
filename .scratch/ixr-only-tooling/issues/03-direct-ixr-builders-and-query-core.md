# 03: Make convenient builders produce IXR directly

Status: resolved
Blocked by: 01, 02

**What to build:** Callers construct readable expressions using Field and composition helpers, and execute them through either adapter with IXR as the sole expression representation. Validation, optimization, and explanation operate on that same representation, as required by the [specification](../spec.md).

- [x] Field, all_of, any_of, not_, and logger-prefix conveniences construct immutable IXR directly; query filters accept that representation.
- [x] Remove Predicate, custom executable subclasses, facade compile/matches/conversion methods, duplicate expression trees, cached facade matchers, and old explanation formats.
- [x] Both adapters compile the exact logical expression stored in the plan. No path uses a callable whose behavior can disagree with advertised IXR.
- [x] Normalization and validation inspect IXR directly, without legacy-type trust checks or wrappers retained solely for old inspection.
- [x] Retained expression, plan, validation, optimization, and coordination responsibilities live in the query core with explicit ownership and no forwarding compatibility modules.
- [x] Public-query tests preserve missing/null, bool/number, structural equality, nested versus literal dotted paths, operand snapshots, finite-value validation, strings/regex/logger prefixes, scalar membership, and supported arrays.
- [x] Preserve semantic operation order, closed-schema dependency errors, static explanation without source consumption, logical error attribution, and conservative rewrite behavior.
- [x] Group-by, named count/sum/mean/min/max, stable sort, empty-input behavior, exact integer arithmetic, and corrected floating reductions continue to work through both adapters where supported.
- [x] Preserve explicit optional-backend capability limits, errors, and native execution without UDF fallback or silent coercion.
- [x] Replace useful standalone predicate tests with public-query or immutable-IXR contract tests, removing assertions tied to facade caching or custom callback compatibility.
- [x] Update affected public expression/query guidance and runnable examples; leave the comprehensive stale-documentation audit to ticket 05.

## Implementation guidance

Ticket 01 establishes the shared contracts and backend ownership consumed here; ticket 02 eliminates callers that would otherwise require predicate compatibility. Do not broaden the expression or query operation vocabulary as part of this representation change.

Ticket 04 is independently ready after the same blockers. Coordinate edits to plan/result definitions, shared rows, adapter wiring, and public exports on integration; there is no semantic dependency between direct IXR construction and separate origins.


## Resolution

Implemented convenient builders as direct immutable IXR construction. Expressions
support boolean composition helpers and `&`, `|`, and `~`; the public tooling
entry point also exports explicit IXR node constructors. Removed the Predicate
facade, duplicate tree, executable callback extension, matcher cache, conversions,
and normalization trust wrappers. Both adapters compile the authoritative
expression stored in each filter.

Expression, builder, plan, validation, normalization, and execution coordination
modules now belong to query core, without compatibility forwarding modules.
Preserved public-query semantic coverage and immutable IXR inspection; replaced
custom callback tests with real query error/resource-lifetime behavior. Updated
expression guidance, changelog, agent navigation, example, and benchmark imports.
Ticket 04 integration additionally ports origin assertions and the agreed strict
zero-limit behavior; its source changes are included in the validated baseline.

Validation on Python 3.13.9 and actual Polars 1.44.2: 319 retained tests pass, Ruff
checks pass for source/tests/examples/benchmarks, and Pyrefly reports zero errors
(33 suppressed). Query example passed before source integration; final runnable
example and Python 3.10 matrix are covered by the final migration verification.
No core logging implementation was modified.

Implementation commit: `2848d70`. Integrated verification baseline: `1101be0`.
