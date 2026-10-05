"""Literal drafts render controls visibly while retaining source cursor indices."""

from __future__ import annotations

from rich.cells import cell_len, get_character_cell_size
from rich.text import Text
from textual.widgets import Input

from .text import draft_text


class DraftInput(Input):
    """Textual input with a one-source-character/one-display-character control map."""

    @property
    def _value(self) -> Text:
        if self.password:
            return super()._value
        text = Text(draft_text(self.value), no_wrap=True, overflow="ignore", end="")
        return self.highlighter(text) if self.highlighter is not None else text

    def _position_to_cell(self, position: int) -> int:
        return cell_len(draft_text(self.value[:position]))

    def _cell_offset_to_index(self, offset: int) -> int:
        offset += self.scroll_offset.x
        cells = 0
        for index, character in enumerate(draft_text(self.value)):
            width = get_character_cell_size(character)
            if cells <= offset < cells + width:
                return index
            cells += width
        return min(max(offset, 0), len(self.value))
