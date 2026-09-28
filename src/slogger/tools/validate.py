"""Validate JSONL log lines against the slogger record schema."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Sequence
from typing import Any

from slogger.schema import validate_log_record
from slogger.tools.reader import Reader, Source, memory_label, resolve_sources


def validate(
    sources: Source | Sequence[Source],
    *,
    max_diagnostics: int = 100,
) -> dict[str, Any]:
    """Validate JSONL lines against :func:`slogger.validate_log_record`.

    Unlike other tools, non-JSON / non-schema lines are reported as failures
    rather than silently skipped.
    """
    resolved = resolve_sources(sources)
    labels: list[str] = []
    mem_index = 0
    for source in resolved:
        if isinstance(source, str):
            labels.append(source)
        else:
            labels.append(memory_label(mem_index))
            mem_index += 1

    reader = Reader(resolved)
    kinds: Counter[str] = Counter()
    diagnostics: list[dict[str, Any]] = []
    diagnostics_capped = False
    lines = 0
    valid = 0
    invalid = 0
    per_source = {
        label: {"lines": 0, "valid": 0, "invalid": 0} for label in labels
    }

    for label, line_no, text in reader.iter_lines():
        lines += 1
        stats = per_source.setdefault(
            label, {"lines": 0, "valid": 0, "invalid": 0}
        )
        stats["lines"] += 1
        kind: str | None = None
        message = ""
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            kind = "not_json"
            message = str(exc)
        else:
            if not isinstance(data, dict):
                kind = "not_object"
                message = f"expected object, got {type(data).__name__}"
            else:
                try:
                    validate_log_record(data)
                except ValueError as exc:
                    kind = "schema"
                    message = str(exc)

        if kind is None:
            valid += 1
            stats["valid"] += 1
            continue

        invalid += 1
        stats["invalid"] += 1
        kinds[kind] += 1
        if len(diagnostics) < max_diagnostics:
            diagnostics.append(
                {
                    "_id": f"{label}:{line_no}",
                    "kind": kind,
                    "message": message,
                }
            )
        else:
            diagnostics_capped = True

    return {
        "schema_version": 1,
        "sources": [
            {
                "path": label,
                "lines": per_source[label]["lines"],
                "valid": per_source[label]["valid"],
                "invalid": per_source[label]["invalid"],
            }
            for label in labels
        ],
        "lines": lines,
        "valid": valid,
        "invalid": invalid,
        "kinds": {
            "not_json": kinds.get("not_json", 0),
            "not_object": kinds.get("not_object", 0),
            "schema": kinds.get("schema", 0),
        },
        "diagnostics": diagnostics,
        "diagnostics_capped": diagnostics_capped,
    }
