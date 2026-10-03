# 03: Make convenient builders produce IXR directly

Status: claimed
Blocked by: 01, 02

**What to build:** Callers construct readable expressions using Field and composition helpers, and execute them through either adapter with IXR as the sole expression representation. Validation, optimization, and explanation operate on that same representation, as required by the [specification](../spec.md).

- [ ] Field, all_of, any_of, not_, and logger-prefix conveniences construct immutable IXR directly; query filters accept that representation.
- [ ] Remove Predicate, custom executable subclasses, facade compile/matches/conversion methods, duplicate expression trees, cached facade matchers, and old explanation formats.
- [ ] Both adapters compile the exact logical expression stored in the plan. No path uses a callable whose behavior can disagree with advertised IXR.
- [ ] Normalization and validation inspect IXR directly, without legacy-type trust checks or wrappers retained solely for old inspection.
- [ ] Retained expression, plan, validation, optimization, and coordination responsibilities live in the query core with explicit ownership and no forwarding compatibility modules.
- [ ] Public-query tests preserve missing/null, bool/number, structural equality, nested versus literal dotted paths, operand snapshots, finite-value validation, strings/regex/logger prefixes, scalar membership, and supported arrays.
- [ ] Preserve semantic operation order, closed-schema dependency errors, static explanation without source consumption, logical error attribution, and conservative rewrite behavior.
- [ ] Group-by, named count/sum/mean/min/max, stable sort, empty-input behavior, exact integer arithmetic, and corrected floating reductions continue to work through both adapters where supported.
- [ ] Preserve explicit optional-backend capability limits, errors, and native execution without UDF fallback or silent coercion.
- [ ] Replace useful standalone predicate tests with public-query or immutable-IXR contract tests, removing assertions tied to facade caching or custom callback compatibility.
- [ ] Update affected public expression/query guidance and runnable examples; leave the comprehensive stale-documentation audit to ticket 05.

## Implementation guidance

Ticket 01 establishes the shared contracts and backend ownership consumed here; ticket 02 eliminates callers that would otherwise require predicate compatibility. Do not broaden the expression or query operation vocabulary as part of this representation change.

Ticket 04 is independently ready after the same blockers. Coordinate edits to plan/result definitions, shared rows, adapter wiring, and public exports on integration; there is no semantic dependency between direct IXR construction and separate origins.
