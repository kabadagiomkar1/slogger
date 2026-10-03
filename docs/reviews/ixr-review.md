# IXR final review resolutions

## Spec review: cancellation-sensitive reductions (P1)

Caller regressions exposed `[1e16, 1.0, -1e16]` returning different floating totals
and means, and million-row repeated fractions drifting beyond the declared tolerance
in grouped native sums. Built-in Python summation also differs between 3.10 and 3.13.

The Python reference now uses `math.fsum` for reductions containing floats, retaining
exact pure-integer accumulation. Native float reductions convert exact binary ratios
to checked common-scale Int128 lanes; Polars performs sums/counts globally or per
group. Final floating conversion applies the power-of-two scale, and means divide
by non-null count. Unsupported scale/range domains raise `data_incompatible`; no
Python UDF or numerical execution fallback is introduced. The initial mixed-sign
rejection proposal was replaced by this lossless conversion, so supported
cancellation-sensitive data executes successfully.

Integer-only mean also divides an exact native Int128 sum by non-null count.
Integer output checks remain intact. Minimum/maximum do not undergo unnecessary
fixed-point domain restrictions. Caller tests cover grouped/ungrouped cancellation,
compensated small contributions, repeated fractional sums, empty/null reductions,
explicit scale/range rejection and exact integer reductions. Capability notes state
the conservative lane bounds and `1e-12` comparison tolerance.

## Standards review: duplicated resolution/projection (P3)

A shared private field-access module now owns the single missing sentinel and
mapping-only nested resolution used by the reference compiler, columnar binder and
reference aggregation. A shared private row helper owns record projection and hidden
identity preservation for both plan adapters. Existing caller tests verify behavior;
no private-helper tests or new public interface were introduced.
