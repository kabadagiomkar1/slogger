# Issue tracker: Local Markdown

Specs and tickets live under `.scratch/<feature-slug>/`.

## Conventions

- Spec: `spec.md`.
- Tickets: `issues/<NN>-<slug>.md`, numbered from 01.
- One file per ticket.
- Record triage state in a `Status:` line near the top.
- Use the vocabulary in `triage-labels.md`.
- Record dependencies as `Blocked by: NN, NN`; use `none`
  when there are no blockers.
- Append discussion under `## Comments`.

## Parallel ticket ownership

Before dispatching tickets concurrently, add `## Coordination` to each overlapping
ticket: list the shared modules/files, the owner of edits to shared contracts,
and which implementer will reconcile tests and imports during integration.
These are execution pointers, not architectural requirements in the spec.
Declare actual semantic blockers in `Blocked by`; file overlap alone is not one.

Record the integration baseline and verified editable environment when claiming
work. Use the development preflight before dispatch, and relay setup/approval
blockers instead of silently duplicating installation attempts.

Superseded specs use `Superseded by: relative/path/to/spec.md` near Status.
Run `python3 scripts/dev.py docs` when resolving work or updating lifecycle state.

## Publishing and reading

Publishing a spec means creating the feature's `spec.md`.
Fetching a ticket means reading its individual issue file.

## Implementation workflow

- Ready frontier: tickets marked `ready-for-agent` whose
  blockers are all `resolved`.
- Claim: set `Status: claimed` before implementation.
- Resolve: record changes and validation under `## Resolution`,
  then set `Status: resolved`.
- Completion: all implementation tickets are resolved.

## Wayfinding

- Map: `.scratch/<effort>/map.md`.
- Decision tickets: `issues/<NN>-<slug>.md`.
- Record kind with `Type: research`, `prototype`, `grilling`,
  or `task`.
- Use the same dependency, claim, and resolution conventions.
- Record decisions under `## Answer` and link them from the map.
