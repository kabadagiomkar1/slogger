# slogger

slogger emits structured log records and provides tooling for querying them.

## Language

**IXR (Intermediate Expression Representation)**:
The execution-independent representation of a structured-log expression, including field references, literal operands, comparisons, and boolean composition.
_Avoid_: legacy predicate tree

**Query plan**:
An ordered description of operations over structured log records, such as filtering, projection, sorting, grouping, and aggregation.

**Record source**:
A finite input of structured log records, supplied through files, stdin, or an iterable.

**Source origin**:
The location of an input log record: a file and line number, or an input label and original position for records supplied by code. It is distinct from the record's position in a query result.

**Console view**:
A compact textual presentation of log records showing timestamp, level, logger,
message, and selected context fields.

**Main filter**:
The condition that determines which log records belong to the main investigation
view and its record search.

**Record search**:
Text matching used to navigate among records admitted by the main filter,
without changing which records that filter admits.
_Avoid_: text filter

**Ancestor context**:
Trace or span structure retained to situate matching records even when the
ancestor's own records are excluded by the main filter.

**Investigation dataset**:
The stable collection of log records captured from the supplied record sources
and shared by an investigation's views; it changes only on explicit refresh.

**Trace**:
A collection of related log records sharing a trace ID across the supplied
record sources.

**Span**:
A named activity within a trace, identified by its span ID and related to an
optional parent span. Span names are labels rather than identities.

**Incomplete span**:
A span whose available records leave lifecycle or parent information absent
from the investigation dataset.

**Conflicting span**:
A span whose records disagree about lifecycle, parent relationships, or
summary information.

**Discovery index**:
A complete dataset-scoped observation of supported field paths and typed scalar
values with occurrence counts. It supplies paged completion choices without
sampling the investigation or changing IXR expression semantics.
