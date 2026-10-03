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
