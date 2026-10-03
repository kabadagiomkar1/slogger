# AGENTS.md

slogger combines a small stdlib-native logging library with independent IXR query tooling.
Keep logging and tooling responsibilities separate.

## Essential constraints

- Preserve the installable src layout. Tests import an installed package.
- Logging exports belong to slogger.__all__; tooling exports belong to slogger.tools.__all__.
- Core logging has no import-time file creation or handler attachment.
- Keep the emitted log schema and logging compatibility imports stable.
- Python 3.10 and 3.13 are the required endpoint checks for attribution or typing changes.
- Update current documentation and changelog when public behavior changes.

## Read when relevant

- Before running checks, setting up worktrees, or dispatching implementers: [development workflow](docs/agents/development.md).
- Before changing logging/configuration/context/schema or logging tests: [logging contracts](docs/agents/logging-contracts.md).
- Before changing query tooling or execution adapters: [tooling ownership](docs/tools-architecture.md) and [capability contract](docs/execution-compatibility.md).
- Before publishing specs or working tickets: [local issue tracker](docs/agents/issue-tracker.md).
- Before assigning triage: [triage labels](docs/agents/triage-labels.md).
- Before domain exploration: [domain documentation](docs/agents/domain.md).
- Before design questions: [interview guidance](docs/agents/design-interviews.md).

Processor pipelines, OTel, sequence tools, framework middleware, and CI remain deferred
unless requested. Preserve formators and slogger compatibility shims. The PyPI name
slogger belongs to another package; see the logging contracts before publishing.
