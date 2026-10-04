# Native Textual prototype

Type: prototype
Status: resolved
Blocked by: 01

## Question

Does layout A work with native terminal input, paged real files, stable reusable
capture storage, and bounded browsing memory? What do cold/warm opening and
1–5 GB resource measurements tell us before production implementation?

## Context

The user confirmed [the complete design](../design-interview.md) and chose this
focused native prototype as the next deliverable. Preserve file order and
first appearance in flat/tree views. Verify contents before automatic reuse;
start with a provisional 10 GB disk budget and configurable RAM cache.

Primary source branch: `codex/tui-visual-prototype`.
Code belongs under `examples/prototypes`, outside the installed library.
Do not claim native SSH behavior from headless/browser evidence.

## Validation

Exercise real-file capture/reuse, navigation and inspector synchronization,
filter/search interactions, folding, and narrow/wide terminal layouts. Measure
representative 100–200 MB files at 1 GB and 5 GB totals. Record limitations and
manual terminal/SSH checks that still need the user's environment.

## Resolution

Built the terminal-only [Textual prototype](../../../examples/prototypes/native_tui.py)
with disk capture/indexing, progressive browsing, verified content reuse,
viewport-only rendering, an inspector, filter-to-IXR translation, disk-backed
filter/search positions, background work/cancellation, and bounded tree preview.
Global presentation defaults and cache cleanup are confined to prototype storage.
No installed library/exports/runtime dependency or production entrypoint changed.

[Usage and limits](../../../examples/prototypes/NATIVE.md),
[measurements](../../../examples/prototypes/native-measurements.md), and
[raw evidence](../../../examples/prototypes/native-measurements.json) accompany
the primary source on `codex/tui-visual-prototype`.

The user explicitly required terminal rather than web; this artifact has no web
interface. Script-only dependencies are optional. Verified Python 3.10/3.13
native smoke runs, 80×24/140×40 headless interactions, actual PTY input, stable
origins/skip counts, content-change detection, and a 10 GB budget protecting an
active 5 GB capture. Shared fast checks pass.

## Answer

This first feasibility version did not meet the user's expectations for polish
or feature parity. The subsequent
[interaction refinement](03-native-interaction-refinement.md) addresses that
review. This ticket's timings remain evidence for the original measured commit,
not acceptance of the revised interface.

Layout A works in native Textual, and paged browsing does not require retaining
the full input in RAM. Local first capture: roughly 7 s at 1 GB and 34 s at 5 GB;
verified reuse: roughly 0.36 s / 2 s. Headless application RSS stayed around
70–75 MiB with a 32 MiB admission budget. These are synthetic local observations.

The 10 GB disk default cannot always hold an active 5 GB dataset and its complete
replacement plus indexes; failure preserves the old dataset. Full autocomplete,
variable-height wrapping, lifecycle reconstruction, aggregates, and atomic
query-preserving refresh remain production work. Actual emulator and SSH behavior
remain an explicit manual validation step; neither browser nor headless evidence
settles them. Review the native artifact before turning the confirmed design into
a production specification.
