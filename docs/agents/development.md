# Development workflow

The shared command is `python3 scripts/dev.py check`. It runs documentation
consistency, Ruff (including benchmarks and development scripts), Pyrefly, and
pytest. `check --fast` omits pytest and is used by the local pre-commit hook.
CI remains deferred. Hooks check the working checkout, including unstaged changes.

## Environment preflight

Before dispatching implementers, verify each checkout's interpreter once:

```sh
python3 scripts/dev.py preflight --python /path/to/environment/bin/python --register
```

The command prints interpreter and dependency versions, imported package location,
and checkout match. It fails if dev tools are missing or slogger imports another
checkout. Registration stores a machine-local interpreter pointer under ignored
`.dev/`; it does not alter imports or install dependencies. Checks repeat this
verification, so a stale environment registration fails clearly.

To provision a checkout-local environment explicitly:

```sh
python3 scripts/dev.py setup --python python3.13 --polars
python3 scripts/dev.py install-hook
```

Setup creates/reuses `.venv`, installs the editable dev extra (and optional Polars),
then registers it. An already verified local environment is reused without another
installation; an explicitly requested different Python version is rejected rather
than silently reusing the wrong interpreter. `--offline` disables package indexes; use a prepared environment
when required packages are unavailable offline. Setup does not retry or download
interpreters automatically. Required network/cache permissions should be settled
in the orchestrator preflight, rather than independently in every subagent.

Interpreter selection is explicit `--python`, then `SLOGGER_PYTHON`, registered
environment, checkout `.venv`, or the command's interpreter. The hook uses this
same selection. Hook installation preserves an existing unrelated hooksPath by
refusing to overwrite it; integrate the check into that hook explicitly instead.

## Native TUI workflow

For changes to the native consumer, provision and check the explicit TUI profile:

```sh
python3 scripts/dev.py setup --python python3.13 --tui
python3 scripts/dev.py check --tui
```

`--tui` installs/requires Textual; a missing dependency fails preflight instead
of silently skipping native tests. `preflight --tui` can verify an existing
environment. Base checks still allow logging/headless development without Textual.
Polars is optional for both profiles: add `--polars` to setup to exercise its
backend as well. Without it, only Polars execution cases skip; Python and native
checks still run, including the explicit missing-dependency contract. The type
checker permits the guarded optional import without suppressing missing imports
elsewhere.
`check --tui --fast` requires Textual but skips all tests; the pre-commit hook
continues to use the existing fast base check.

After docs, Ruff and Pyrefly, the TUI profile runs the focused rendered interaction
suite with `pytest -x`. It covers visible drafts at narrow/wide sizes and both
themes, completion placement and routing, keyboard/mouse focus, Enter/Escape,
settings/palette dismissal, search highlighting, aggregates, and short/long
viewport navigation. A failure stops before the full suite. Once it passes, the
full suite runs once. For a known regression, first run its specific pytest node
with `-x`; broaden after resolving it. These checks precede scale measurements.
Actual terminal/SSH acceptance remains a separate [manual exercise](../terminal-validation.md).

Native tests must wait for the state they exercise: a published result/mode flag
can precede terminal layout. Before navigation, verify stable viewport dimensions,
focus, and rendered result rows; before completion actions, verify menu publication.
Use bounded state checks rather than assuming one event-loop turn is enough.

Every `check` saves streamed logs, pytest JUnit reports, commands, timings, failure
case names, environment versions, Git revision and working-tree status under
ignored `.dev/checks/<UTC time>/report.json`. Supply `--report-dir /path/to/new-dir`
to retain evidence elsewhere; an existing destination is refused. The JSON marks
the whole run passed/failed, including early failure. A dirty checkout's evidence
describes uncommitted changes, not proof for its HEAD alone. Read the actual
failure output before classifying it; progress dots are not diagnosis. Preflight
failure prints its diagnostic before a check report is created. Logs and reports
are local artifacts; remove old run directories when they are no longer needed.

Test runs announce whether Polars coverage is enabled and print each test's name
and status. Each stage ends with separate counts for passed/failed/error outcomes,
expected failures, skipped individual tests, and whole modules not collected.
Module skips include the module name and reason; their contained tests cannot be
counted in that environment. `report.json` retains per-stage `test_summary` and
`test_outcomes` entries with node ID, test/module scope, outcome, and skip/error
reason. The focused TUI stage and full suite remain separate inventories, since
they deliberately overlap. `--fast` explicitly states that tests are disabled.

Performance runs use small fixtures and bounded phases before considering 1–5 GB.
The [qualification runner](../../benchmarks/investigation_qualification.py) defaults
to `--phase-timeout 300`: a timed-out phase aborts the run and retains partial
evidence. Override explicitly for deliberate long characterization runs. Full
discovery time is distinct from capture/startup time; do not repeat an expensive
phase merely to establish a known usability problem.

## Parallel work and progress

Record the verified environment and integration baseline in implementer context
pointers. Each worktree needs an editable installation pointing at that worktree;
verification-only agents can reuse a primary environment when their committed
code is identical, and must record that equivalence in their evidence.

Report setup, running checks, pending approval, or blocked state at a task boundary.
An orchestrator should investigate a silent setup before dispatching duplicate
installs: inspect whether an approval is pending and resume with a verified
environment when appropriate. Elapsed time never grants approval. Share check
artifacts by path and revision, not by repeating their entire output.

For parallel tickets, declare shared-file ownership and merge coordination in the
ticket. Keep semantic dependencies separate from files that merely overlap.

## Deeper verification

Run the shared command on Python 3.10 and 3.13 where the change requires endpoint
coverage. Enable actual Polars in adapter environments and separately verify a
base environment without it. For performance work, run the documented benchmark
matrix; timings and memory belong to the measured revision. Documentation-only
changes need docs/link checks, not a new benchmark run.

## Documentation lifecycle

`python3 scripts/dev.py docs` checks maintained local Markdown links, ticket
dependency cycles/unknown blockers, and implemented specs with unresolved tickets.
Historical documents have an explicit historical notice near their title;
removed file references in those snapshots are not checked as current guidance.

Add `Superseded by: relative/path/to/spec.md` beside a superseded spec's Status.
The checker follows that source of truth and rejects introductory claims that
an implemented successor is forthcoming or not yet implemented. It checks local
file targets, not external sites or Markdown anchors. Keep judgement about whether
documentation explains the behavior accurately in code review.
