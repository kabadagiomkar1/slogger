"""Validate the JSON Schema subset used by the bundled tool contracts."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any


def validate_schema(value: Any, schema: Any, *, root: Mapping[str, Any], path: str) -> None:
    if schema is True:
        return
    if schema is False:
        raise ValueError(f"{path}: value is not allowed")
    if "$ref" in schema:
        target: Any = root
        for part in schema["$ref"].removeprefix("#/").split("/"):
            target = target[part]
        validate_schema(value, target, root=root, path=path)
        return
    if "anyOf" in schema:
        for option in schema["anyOf"]:
            try:
                validate_schema(value, option, root=root, path=path)
                return
            except ValueError:
                continue
        raise ValueError(f"{path}: no allowed shape matches")
    choices = schema.get("enum", [schema["const"]] if "const" in schema else None)
    if choices is not None and not any(
        value == choice and isinstance(value, bool) == isinstance(choice, bool)
        for choice in choices
    ):
        raise ValueError(f"{path}: expected one of {choices!r}")
    kind = schema.get("type")
    if kind is not None:
        kinds = [kind] if isinstance(kind, str) else kind
        numeric = isinstance(value, (int, float)) and not isinstance(value, bool)
        matches = {
            "null": value is None,
            "boolean": isinstance(value, bool),
            "string": isinstance(value, str),
            "integer": numeric and (isinstance(value, int) or value.is_integer()),
            "number": numeric and (isinstance(value, int) or math.isfinite(value)),
            "array": isinstance(value, list),
            "object": isinstance(value, Mapping),
        }
        if not any(matches.get(item, False) for item in kinds):
            raise ValueError(f"{path}: must have type {kind!r}")
    if isinstance(value, Mapping):
        missing = set(schema.get("required", ())) - value.keys()
        if missing:
            raise ValueError(f"{path}: missing required key(s): {sorted(missing)}")
        properties = schema.get("properties", {})
        extra = schema.get("additionalProperties", True)
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{path}: object keys must be strings")
            validate_schema(item, properties.get(key, extra), root=root, path=f"{path}.{key}")
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            raise ValueError(f"{path}: too few items")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            raise ValueError(f"{path}: too many items")
        for index, item in enumerate(value):
            validate_schema(item, schema.get("items", True), root=root, path=f"{path}[{index}]")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            raise ValueError(f"{path}: must be >= {schema['minimum']}")
        if "exclusiveMinimum" in schema and value <= schema["exclusiveMinimum"]:
            raise ValueError(f"{path}: must be > {schema['exclusiveMinimum']}")
