"""Lossless JSON spellings suitable for human-entered query tokens and views."""

from __future__ import annotations

import json

_JSON_CONTROLS = {code: f"\\u{code:04x}" for code in range(127, 160)}


def json_spelling(
    value: object,
    *,
    indent: int | None = None,
    separators: tuple[str, str] | None = None,
    allow_nan: bool = True,
) -> str:
    """Keep Unicode readable while representing DEL/C1 as equivalent JSON escapes."""
    return json.dumps(
        value, ensure_ascii=False, indent=indent, separators=separators, allow_nan=allow_nan
    ).translate(_JSON_CONTROLS)
