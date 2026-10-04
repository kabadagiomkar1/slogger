"""Visible source text; original records and semantic token offsets stay separate."""

from __future__ import annotations

import io
import re

_CONTROLS = re.compile(r"[\x00-\x1f\x7f-\x9f]")


def character_spelling(character: str, column: int, *, multiline: bool = False) -> tuple[str, int]:
    if multiline and character == "\n":
        return character, 0
    if multiline and character == "\t":
        fragment = " " * (4 - column % 4)
    elif ord(character) < 32 or 127 <= ord(character) <= 159:
        fragment = f"\\u{ord(character):04x}"
    else:
        fragment = character
    return fragment, column + len(fragment)


def visible_text(value: str, *, multiline: bool = False, column: int = 0) -> str:
    if not _CONTROLS.search(value):
        return value
    fragments = io.StringIO()
    for character in value:
        fragment, column = character_spelling(character, column, multiline=multiline)
        fragments.write(fragment)
    return fragments.getvalue()


# Single-codepoint control pictures keep a draft's source indices unchanged.
_DRAFT_CONTROLS = {
    code: chr(0x2400 + code) if code < 32 else "␡" if code == 127 else "�"
    for code in (*range(32), *range(127, 160))
}


def draft_text(value: str) -> str:
    return value.translate(_DRAFT_CONTROLS)
