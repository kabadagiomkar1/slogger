# IXR-only tooling verification

Verification date: 2026-10-03. Implementation measured:
`4b777b0001d6a15c4387ae0872fdc16b3610a651` on integration branch
`codex/ixr-only-tooling`. This report records delivery verification, not the
subsequent Standards/Spec code review.

## Installed-package verification

- Python 3.13.9 / Polars 1.44.2: full retained suite, **319 passed**.
- Python 3.10.20 / Polars 1.29.0: full retained suite, **319 passed**.
- Both suites used existing editable installations pointing at the integration
  checkout, whose committed code equals the ticket-06 worktree baseline. No
  PYTHONPATH or source-path import adjustment was used.
- Ruff checked source, tests, examples, and the benchmark driver: all checks passed.
- Pyrefly checked the configured Python 3.10 contract: zero errors, 33 suppressed.
- The base Python 3.13 installation ran the query example without Polars. Actual
  Polars execution ran the same example explicitly. Both preserve origins through
  filtering/projection and produce absent origins for grouped summaries.
- Basic, named-logger, span, thread-context, stdlib-integration, and division demos
  completed in a temporary directory. The optional HTTP server demo was not
  started; its dependencies and server lifecycle are outside this migration.

The behavioral suite covers missing/null and bool/number distinctions, explicit
paths, operand snapshots, regex/arrays, schema lineage, operation order, stable
sort/group identity, sparse reconstruction, exact integers, floating cancellation,
post-aggregation operations, source diagnostics, physical origins, iterable
positions, one-shot input, zero limits, and owned resource lifetime. Capability
and incompatible-data failures remain explicit; neither adapter falls back.

## Built distribution

A wheel was built with system Python and setuptools 80.4 using
`python -m build --wheel --no-isolation`. Its archive contains the typed marker,
core log-record schema, and retained ownership modules. Retired CLI/MCP modules,
legacy filtering/reader/predicate modules, transport schema, and transport-only
extras are absent. The optional Polars extra remains explicit.

The actual wheel was installed with `pip --no-index --no-deps` into an isolated
Python 3.13.3 environment. Import came from site-packages with Polars absent.
Core capture_logs emission and builtin_logger/instrument compatibility imports
worked. A direct IXR query preserved an application _id and exposed source origin
at position zero. Selecting Polars raised the dependency_missing tooling error.
The packaged log-record schema was accessible.

## Ownership and documentation audit

Core expressions, plans, normalization/validation, execution coordination, and
runtime contracts reside in the query core; finite source parsing and ordering
reside in sources; Python and Polars execution remain separate internal adapters.
No legacy forwarding facade remains. Compared with the pre-migration baseline,
retained core logging code, root exports, and compatibility shims are unchanged;
the package-root docstring only removes retired tooling references. Removed
entry-point modules and transport schema belong to the authorized tooling cutover.

Maintained API, capability, architecture, README, examples, and benchmark guidance
contain no runnable retired imports. Historical plans carry prominent supersession
notices. Relative Markdown file links in README, AGENTS, benchmark guidance, and
docs resolve. The completed earlier specification remains historical baseline
rather than current compatibility guidance.

## Performance evidence and limits

The [benchmark report](../../benchmarks/README.md) and
[raw version-2 matrix](../../benchmarks/results/ixr-only-2026-10-03.json) record
sixteen cases, two input sizes (200/100,000), both adapters, three repeats, timing
and worker peak RSS, with aligned record/origin digest checks. All checks passed.
Python had lower repeated medians and RSS in this tested matrix. No general
speedup, isolated origin overhead, disk-cache control, or intermediate Polars
version coverage is claimed. Independent probes overlap and must not be summed.

This verification adds evidence and lifecycle documentation only; no behavioral
regression required a new test or implementation change. Further changes from
code review must be checked against the affected public query behavior.
