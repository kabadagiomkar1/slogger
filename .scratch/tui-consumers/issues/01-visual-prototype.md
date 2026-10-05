# TUI visual and interaction prototype

Type: prototype
Status: resolved
Blocked by: none

## Question

How should the console stream, trace navigation, JSON inspector, search,
query editor, aggregates, and global preferences fit together in a terminal UI?

## Context

Primary source branch: `codex/tui-visual-prototype`.
Prototype: `examples/prototypes/tui-prototype.html`.
Run: `python3 examples/prototypes/serve_tui.py`.
Single route with `?variant=A`, `?variant=B`, or `?variant=C`.

This is a browser sketch of a terminal interface, using synthetic finite logs
and an intentionally limited mock filter parser. It does not connect to IXR,
read supplied files, or save preferences. Global settings are simulated in memory.

## Answer

The user selected A (split inspector): it provides vertical space for records,
and hiding the JSON inspector recovers horizontal space. Other presented
interactions were accepted as the starting concept. Keep B and C on the
prototype branch as comparison evidence.

Filter completion must cover syntax as well as observed keys and values:
operators, boolean connectors, presence functions, grouping, and typed values.
The revised mock editor demonstrates contextual suggestions with up/down
selection, Tab completion, and Enter to accept a selected suggestion or apply.
The final language still needs a deliberate contract covering IXR filtering.

Terminal mouse support and SSH operation are requirements for the future TUI.
Every mouse interaction must also have a keyboard route. Horizontal gestures,
clipboard access, appearance, and latency depend on the terminal/connection;
browser smoothness is not an accepted guarantee of terminal behavior.

## Delivery

The interactive artifact is complete; layout A has been selected by the user.
It includes three layouts, guided flows, keyboard record navigation, separate
search and mock filtering, field/value suggestions, trace folding with ancestor
context and missing-parent indicators, pinned JSON inspection, field aggregates
with following/independent scopes, and simulated global settings.

Browser verification covered search within filtered results, trace context,
layout switching, field selection, independent aggregate scope, wrapping,
simulated defaults, and invalid-query feedback retaining prior results.
Browser error logs were empty. No tests were added for throwaway code.

The revised completion flow was verified in the browser: numeric operator
suggestions, up/down and Tab insertion, observed-value suggestions, AND/OR
suggestions, and operator completion inside a second clause. Browser error
logs remained empty; the repository fast checks passed.

## Resolution

Captured the accepted layout and interaction direction on the prototype branch.
The browser artifact remains throwaway; no production TUI has been implemented.

## Comments

Three structural alternatives: split inspector, trace workbench, and wide console
with a bottom inspection dock. The floating comparison controls are prototype-only.
