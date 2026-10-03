---
status: accepted
---

# Migrate tooling to IXR without legacy compatibility

The existing tooling retains a legacy filtering route alongside IXR query execution. The next migration will make IXR the sole expression representation, with convenient builders constructing it directly, and remove the legacy filters, specialized analysis tools, CLI, and MCP rather than adapting their contracts. This accepts breaking changes to reduce duplicate expression state and compatibility obligations; specialized capabilities and transports can be redesigned on IXR later. The core logging library remains unchanged.

Finite input conveniences remain in scope: files, globs, stdin, record iterables, concatenation, and time merging. Removing specialized tools does not imply removing their independently useful source handling.

Source origin will be exposed alongside records rather than inserted into their application fields. Filtering, projection, and sorting will preserve that origin. The execution adapter interface will remain internal initially; Python and optional Polars continue to implement the shared IXR semantics without a public adapter-registration contract.

This decision supersedes the compatibility-preservation requirements of the earlier IXR specification for the forthcoming migration. It records the agreed design direction; the current implementation still contains the legacy tooling until the migration is implemented.
