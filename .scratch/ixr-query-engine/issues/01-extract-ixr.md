# 01: Extract IXR behind existing predicates

**What to build:** Callers can inspect immutable, execution-independent expressions while existing predicate construction and Python matching retain their behavior.

**Blocked by:** None (can start immediately)

**Status:** resolved

**Parent specification:** IXR and query execution specification (local tracker, same feature).

**Scope:** Python tooling only; preserve core logging and existing CLI/MCP inputs.

- [x] Field/composition helpers produce frozen typed IXR with explicit paths, dependencies, and versioned inspection; logical nodes contain no executable callbacks or native dataframe objects.
- [x] All existing operators preserve missing/null, boolean/number, structural equality, empty-expression, and array semantics; mutable operands are snapshotted and invalid operands/regexes fail at construction.
- [x] Predicate.to_ixr is available; Python compilation is lazy and returns a reusable cached matcher. Existing Predicate.explain descriptions and Filters/Where behavior remain compatible.
- [x] Existing custom Predicate subclasses remain instantiable and usable for Python matching; unsupported IXR extraction reports a clear error.
- [x] Tests through Predicate and Filters demonstrate unchanged tooling behavior, and documentation distinguishes new IXR inspection from existing inspection-only mapping contracts.

## Resolution

Implemented immutable IXR nodes with typed snapshots, explicit paths, dependency
analysis and version-one inspection; extracted the lazy cached Python compiler.
Preserved legacy inspection and custom-subclass matching. Updated interface docs
and delivery status.

Validation: 311 tests passed on Python 3.10 and 3.13; Ruff and Pyrefly passed; CLI
help and diff whitespace checks passed.
