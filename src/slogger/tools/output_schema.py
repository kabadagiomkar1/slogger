"""Published JSON contracts for :mod:`slogger.tools` aggregate outputs.

The schema document lives at ``slogger/schemas/tool-output.schema.json``.
:func:`validate_tool_output` checks the constraints in the bundled schemas without
depending on the ``jsonschema`` package (same spirit as
:func:`slogger.validate_log_record`).
"""

from __future__ import annotations

import json
from importlib import resources
from typing import Any, Literal, Mapping, cast, get_args

from slogger.tools._schema import validate_schema

ToolOutputKind = Literal[
    "meta",
    "fields",
    "fields_top",
    "summary",
    "tree",
    "stats",
    "errors",
    "validate",
    "diff",
    "trace",
    "explain",
    "page_meta",
    "watch_meta",
]

def output_schemas() -> dict[str, Any]:
    """Return the tool-output JSON Schema (draft 2020-12) document."""
    schema_path = resources.files("slogger").joinpath("schemas").joinpath(
        "tool-output.schema.json"
    )
    with schema_path.open(encoding="utf-8") as handle:
        return cast(dict[str, Any], json.load(handle))


def validate_tool_output(kind: ToolOutputKind, data: Mapping[str, Any]) -> Mapping[str, Any]:
    """Check that ``data`` matches the published contract for ``kind``.

    Extra keys are allowed. Raises :class:`ValueError` when required fields are
    missing or violate the published types and nested constraints. Does not require ``jsonschema``.
    """
    schemas = output_schemas()
    if kind not in get_args(ToolOutputKind):
        raise ValueError(f"unknown tool output kind: {kind!r}")
    validate_schema(data, schemas["$defs"][kind], root=schemas, path=kind)

    return data


__all__ = [
    "ToolOutputKind",
    "output_schemas",
    "validate_tool_output",
]
