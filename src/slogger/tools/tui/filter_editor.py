"""Consumer draft/applied/pending editor state over the shared infix parser."""

from __future__ import annotations

from textual import events
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.widgets import Input, OptionList, Static
from textual.widgets.input import Selection
from textual.widgets.option_list import Option

from ..core.filter_language import (
    FilterCompletion,
    FilterSyntaxError,
    complete_filter,
    parse_filter,
)
from ..core.ixr import Expression


class FilterInput(Input):
    """Input keeps Tab for completion only while its own menu is visible."""

    class PositionChanged(Message):
        pass

    def __init__(self, editor: FilterEditor, **kwargs):
        super().__init__(**kwargs)
        self.editor = editor

    def watch_selection(self, selection: Selection) -> None:
        self.post_message(self.PositionChanged())

    def watch_has_focus(self, _has_focus: bool) -> None:
        super().watch_has_focus(_has_focus)
        self.post_message(self.PositionChanged())

    def on_key(self, event: events.Key) -> None:
        if self.editor.handle_completion_key(event.key):
            event.stop()
            event.prevent_default()


class FilterEditor(Vertical):
    """Reusable compact native editor. Jobs and successful views belong to its owner."""

    DEFAULT_CSS = """
    FilterEditor { height: 2; }
    FilterEditor Horizontal { height: 1; }
    FilterEditor .filter-label { width: 6; height: 1; content-align: center middle; }
    FilterEditor Input { width: 1fr; height: 1; border: none; padding: 0 1; }
    FilterEditor OptionList {
        display: none; overlay: screen; position: absolute; offset: 6 1;
        width: 60; max-width: 90%; height: auto; max-height: 7;
        border: round $primary-muted; padding: 0; background: $panel;
    }
    FilterEditor .filter-status { height: 1; padding: 0 1; color: $text-muted; }
    """

    class ApplyRequested(Message):
        def __init__(
            self, editor: FilterEditor, text: str, expression: Expression, generation: int
        ):
            super().__init__()
            self.editor = editor
            self.text = text
            self.expression = expression
            self.generation = generation

    def __init__(
        self, *, id: str = "main-editor", input_id: str = "main-filter", label: str = "Main"
    ):
        super().__init__(id=id)
        self.input_id = input_id
        self.draft_generation = 0
        self._completion_revision = 0
        self.completion: FilterCompletion = complete_filter("")
        self._dismissed: tuple[str, int] | None = None
        self.label = label
        self.applied_text = ""
        self.applied_expression = parse_filter("")
        self.pending_text: str | None = None
        self.pending_generation: int | None = None
        self.generation = 0
        self.status_text = "Applied: all records · F4 edit · Enter apply · Esc cancel"
        self._status_base = self.status_text

    @property
    def draft(self) -> str:
        return self.query_one(Input).value

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield Static(self.label, classes="filter-label", markup=False)
            yield FilterInput(
                self,
                placeholder='level == "ERROR" AND message contains "timeout"',
                id=self.input_id,
            )
        yield Static(self.status_text, classes="filter-status", markup=False)
        yield OptionList(classes="filter-completions", markup=False)

    def show_status(self, text: str) -> None:
        self._status_base = text
        self.render_status()

    def render_status(self) -> None:
        text = self._status_base
        if self.is_mounted and self.query_one(Input).has_focus and self.completion.guidance:
            text += " · " + self.completion.guidance
            if self.query_one(OptionList).display:
                text += " · ↑↓ Tab · Esc dismiss"
        self.status_text = text
        self.query_one(".filter-status", Static).update(text)

    def on_input_changed(self, message: Input.Changed) -> None:
        message.stop()
        self.draft_generation += 1
        if self._dismissed is not None and message.value != self._dismissed[0]:
            self._dismissed = None
        self.update_completion()
        applied = self.applied_text or "all records"
        if self.pending_text is not None:
            state = " · draft changed" if message.value != self.pending_text else ""
            self.show_status(
                f"Pending: {self.pending_text or 'all records'} · Applied: {applied}{state}"
            )
        elif message.value != self.applied_text:
            self.show_status(f"Draft · Applied: {applied} · Enter apply")
        else:
            self.show_status(f"Applied: {applied} · F4 edit · Enter apply · Esc cancel")

    def on_input_submitted(self, message: Input.Submitted) -> None:
        message.stop()
        self.dismiss_completion()
        try:
            expression = parse_filter(message.value)
        except FilterSyntaxError as error:
            self.show_status(
                f"Draft error: {error} · Applied: {self.applied_text or 'all records'}"
            )
            return
        self.generation += 1
        self.post_message(self.ApplyRequested(self, message.value, expression, self.generation))

    def begin(self, text: str, generation: int) -> None:
        self.pending_text = text
        self.pending_generation = generation
        self.show_status(
            f"Pending: {text or 'all records'} · Applied: {self.applied_text or 'all records'}"
        )

    def publish(self, text: str, expression: Expression, generation: int) -> bool:
        if self.pending_generation != generation:
            return False
        self.applied_text = text
        self.applied_expression = expression
        self.pending_text = None
        self.pending_generation = None
        state = " · draft changed" if self.draft != text else ""
        self.show_status(f"Applied: {text or 'all records'}{state}")
        return True

    def fail(self, generation: int, reason: str) -> None:
        if self.pending_generation == generation:
            self.pending_text = None
            self.pending_generation = None
            self.show_status(f"{reason} · Applied: {self.applied_text or 'all records'}")

    def on_filter_input_position_changed(self, message: FilterInput.PositionChanged) -> None:
        message.stop()
        if self.is_mounted:
            self.update_completion()

    def update_completion(self) -> None:
        entry = self.query_one(Input)
        self.completion = complete_filter(
            entry.value, entry.cursor_position, generation=self.draft_generation
        )
        menu = self.query_one(OptionList)
        self._completion_revision += 1
        menu.clear_options()
        menu.add_options(
            Option(choice.label, id=f"{self._completion_revision}:{index}")
            for index, choice in enumerate(self.completion.choices)
        )
        menu.can_focus = False
        menu.display = (
            bool(self.completion.choices)
            and entry.has_focus
            and (self._dismissed != (entry.value, entry.cursor_position))
        )
        menu.highlighted = 0 if self.completion.choices else None
        self.render_status()

    def dismiss_completion(self) -> None:
        entry = self.query_one(Input)
        self._dismissed = (entry.value, entry.cursor_position)
        self.query_one(OptionList).display = False
        self.render_status()

    def handle_completion_key(self, key: str) -> bool:
        menu = self.query_one(OptionList)
        if key == "ctrl+space":
            self._dismissed = None
            self.update_completion()
            return True
        if not menu.display:
            return False
        if key == "escape":
            self.dismiss_completion()
            return True
        if key in ("up", "down"):
            step = 1 if key == "down" else -1
            menu.highlighted = ((menu.highlighted or 0) + step) % len(self.completion.choices)
            return True
        if key == "tab":
            self.accept_completion(menu.highlighted or 0)
            return True
        return False

    def accept_completion(self, index: int) -> bool:
        entry = self.query_one(Input)
        if not 0 <= index < len(self.completion.choices):
            return False
        edit = self.completion.apply(
            self.completion.choices[index],
            text=entry.value,
            cursor=entry.cursor_position,
            generation=self.draft_generation,
        )
        if edit is None:
            self.update_completion()
            return False
        entry.value, entry.cursor_position = edit
        entry.focus()
        self._dismissed = None
        return True

    def on_option_list_option_selected(self, message: OptionList.OptionSelected) -> None:
        message.stop()
        if message.option.id == f"{self._completion_revision}:{message.option_index}":
            self.accept_completion(message.option_index)
