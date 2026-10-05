# Aggregate selected-field presence

Type: prototype
Status: resolved
Blocked by: 04

## Problem

The user found aggregate outcomes misleading because records missing the selected
field still contributed to counts. Restrict each aggregate to records where its
selected field exists, within the main or independent filter.

Primary source branch: `codex/tui-visual-prototype`. Baseline: `85ca2b9`.
Scope remains the throwaway native prototype; public IXR behavior is unchanged.

## Resolution

The batched aggregate query applies the selected field's IXR `exists()` expression
before collecting eligible records or enforcing the preview budget. Count, value
groups, and numeric metrics now share that presence-restricted scope. The pane's
scope note explicitly includes `exists(field)`.

Nested and quoted literal-key paths use the same IXR presence semantics.
Explicit null remains present: it counts as a record/value group, while numeric
reductions skip null. Zero and false remain present values. Other grouping keys
retain their existing missing/null behavior; this change restricts the selected
aggregate field without silently adding filters for other keys.

## Validation

An exploratory harness reproduced the problem: 10 records with 5 present amount
fields produced count 10. After the change, count is 5, sum 80, mean 20, min 0,
and max 50. Python 3.10.20 and 3.13.9 runs also checked value counts without a
missing selected-field group, numeric grouping, explicit null/zero/false, nested paths,
literal keys, entirely absent fields, and main/independent filter composition.
An eligible amount after 10,001 missing-field records is still included: preview
limits count eligible records after the presence restriction.

A native headless pane using the demo's sparse amount field reports only records
containing amount (2 records) and leaves the 54-record console scope intact. Repository
documentation/Ruff/Pyrefly checks pass; no public execution adapter changed.

## Answer

Aggregates now summarize only records containing the selected field, and disclose
that scope. The remaining prototype limits in
[native usage](../../../examples/prototypes/NATIVE.md) still apply.
