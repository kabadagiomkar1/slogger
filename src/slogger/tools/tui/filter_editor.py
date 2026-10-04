"""Consumer draft/applied/pending editor state over the shared infix parser."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.widgets import Input, Static

from ..core.filter_language import FilterSyntaxError, parse_filter
from ..core.ixr import Expression


class FilterEditor(Vertical):
    """Reusable compact native editor. Jobs and successful views belong to its owner."""

    DEFAULT_CSS = """
    FilterEditor { height: 2; }
    FilterEditor Horizontal { height: 1; }
    FilterEditor .filter-label { width: 6; height: 1; content-align: center middle; }
    FilterEditor Input { width: 1fr; height: 1; border: none; padding: 0 1; }
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
        self.label = label
        self.applied_text = ""
        self.applied_expression = parse_filter("")
        self.pending_text: str | None = None
        self.pending_generation: int | None = None
        self.generation = 0
        self.status_text = "Applied: all records · F4 edit · Enter apply · Esc cancel"

    @property
    def draft(self) -> str:
        return self.query_one(Input).value

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield Static(self.label, classes="filter-label", markup=False)
            yield Input(
                placeholder='level == "ERROR" AND message contains "timeout"', id=self.input_id
            )
        yield Static(self.status_text, classes="filter-status", markup=False)

    def show_status(self, text: str) -> None:
        self.status_text = text
        self.query_one(".filter-status", Static).update(text)

    def on_input_changed(self, message: Input.Changed) -> None:
        message.stop()
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
