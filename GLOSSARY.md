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
