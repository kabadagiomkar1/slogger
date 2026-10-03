---
status: accepted
---

# Stable datasets for the planned TUI

The planned TUI targets investigations totaling 1–5 GB, with typical source
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

This records an accepted design for a future consumer. The current IXR backend
still returns materialized results and has no stable investigation dataset
interface. Temporary storage alone does not make execution bounded-memory;
the implementation must address result delivery and working memory as well.
