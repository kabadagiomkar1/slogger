"""Byte-bounded file lines with UTF-8 text-source universal-newline semantics."""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import BinaryIO

from ..errors import ToolError

_NEWLINE = re.compile(rb"\r\n|\r|\n")


def bounded_lines(stream: BinaryIO, byte_length: int, max_line_bytes: int) -> Iterator[bytes]:
    """Yield complete physical lines up to an exact byte boundary, with bounded buffering."""
    position = 1
    remaining = byte_length
    pending = bytearray()
    while remaining:
        chunk = stream.read(min(remaining, 64 * 1024, max_line_bytes + 1))
        if not chunk:
            raise ToolError(
                "source_changed",
                "Source truncated within its opening byte boundary.",
                position=position,
            )
        remaining -= len(chunk)
        pending.extend(chunk)
        start = 0
        for match in _NEWLINE.finditer(pending):
            if match.end() == len(pending) and pending[match.start()] == 13 and remaining:
                break  # A CRLF may straddle the next block.
            end = match.end()
            if end - start > max_line_bytes:
                raise ToolError(
                    "record_too_large", "Source line exceeds max_record_bytes.", position=position
                )
            yield bytes(pending[start:end])
            position += 1
            start = end
        del pending[:start]
        if len(pending) > max_line_bytes:
            raise ToolError(
                "record_too_large", "Source line exceeds max_record_bytes.", position=position
            )
    if pending:
        yield bytes(pending)
