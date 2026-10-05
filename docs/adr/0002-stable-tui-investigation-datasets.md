---
status: accepted
---

# Stable datasets for native investigations

The native design targets investigations totaling 1–5 GB, with typical source
files around 100–200 MB. An investigation uses a stable dataset until the user
explicitly refreshes. It retains captured data in disk storage
and uses a RAM cache for browsing, rather than retaining the entire decoded
dataset in RAM. This trades additional disk space and I/O for a memory footprint
that can be bounded independently of input size.

The captured dataset retains source origins separately from application fields.
Capture boundaries are established when opening the supplied files; later
appends require refresh. Progressive browsing and inspection are supported
while capture continues. Search, filtering, trees, and aggregates wait for
complete capture. Failed refresh preserves the previous complete dataset;
successful refresh preserves investigation settings and restores selected or
pinned records only when their identity is verified.

Completed datasets remain in a bounded reusable disk cache across launches,
with a configurable storage budget and inactivity expiry. Protect datasets in
use, clean failed or abandoned captures, and expose cache usage and a clear
action. Each process creates its own RAM cache. Reuse may avoid copying,
decoding, and indexing. Verify source contents before automatic reuse, even
when this requires a full read. Start with a provisional configurable 10 GB
total disk budget including indexes and staging, and seven-day inactivity
expiry. RAM cache size can be increased; its exact default awaits measurement.
Reopening speed and actual storage/memory usage are not yet measured.
Global settings persist; query, search,
and navigation histories initially remain within a session.

This records the accepted design. Production tickets 06–22 provide the headless
stable Investigation operations and optional native split view; see the [opening contract](../native-investigation.md).
Capture supports progressive background loading, verification, cancellation and
retained incomplete prefixes. Explicit durable headless storage and the native
default cache now provide source/capture hashing, process leases, global allocation
admission and safe expiry/clear. Explicitly scoped background filters, search,
complete discovery, trace trees and aggregates now use bounded working memory and
disk-backed complete result delivery. Atomic refresh stages and verifies a new owner
before native publication, retaining old data during pending or failed work.
Actual terminal/SSH validation and 1–5 GB resource qualification remain pending in
tickets 23 and 24.
The public IXR `QueryPlan.execute()` still returns materialized results.
Investigation operations have their own bounded delivery/admission contracts;
these do not change the materialized QueryPlan API or establish a measured
whole-process resource envelope.
