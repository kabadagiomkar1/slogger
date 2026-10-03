# TUI visual and interaction prototype

Type: prototype
Status: ready-for-human
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

Pending user evaluation. No layout or interaction has been accepted for production.

## Delivery

The interactive artifact is complete; layout selection remains for the user.
It includes three layouts, guided flows, keyboard record navigation, separate
search and mock filtering, field/value suggestions, trace folding with ancestor
context and missing-parent indicators, pinned JSON inspection, field aggregates
with following/independent scopes, and simulated global settings.

Browser verification covered search within filtered results, trace context,
layout switching, field selection, independent aggregate scope, wrapping,
simulated defaults, and invalid-query feedback retaining prior results.
Browser error logs were empty. No tests were added for throwaway code.

## Comments

Three structural alternatives: split inspector, trace workbench, and wide console
with a bottom inspection dock. The floating comparison controls are prototype-only.
