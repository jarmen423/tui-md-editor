"""Provides a modal dialog for finding text in the editor."""

from __future__ import annotations

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label


class FindDialog(ModalScreen[tuple[str, bool] | None]):
    """A modal dialog for finding text in the editor."""

    DEFAULT_CSS = """
    FindDialog {
        align: center middle;
    }

    FindDialog > Vertical {
        background: $panel;
        height: auto;
        width: auto;
        border: thick $primary;
    }

    FindDialog > Vertical > * {
        width: auto;
        height: auto;
    }

    FindDialog Input {
        width: 40;
        margin: 1;
    }

    FindDialog Label {
        margin-left: 2;
    }

    FindDialog Button {
        margin-right: 1;
    }

    FindDialog #buttons {
        width: 100%;
        align-horizontal: right;
        padding-right: 1;
    }
    """

    BINDINGS = [
        Binding("escape", "app.pop_screen", "", show=False),
    ]

    def __init__(self, initial: str | None = None) -> None:
        """Initialise the find dialog.

        Args:
            initial: The initial search term.
        """
        super().__init__()
        self._initial = initial or ""

    def compose(self) -> ComposeResult:
        """Compose the child widgets."""
        with Vertical():
            with Vertical(id="input"):
                yield Label("Find:")
                yield Input(self._initial)
            with Horizontal(id="buttons"):
                yield Button("Previous", id="previous")
                yield Button("Next", id="next", variant="primary")
                yield Button("Cancel", id="cancel")

    def on_mount(self) -> None:
        """Set up the dialog once the DOM is ready."""
        self.query_one(Input).focus()

    @on(Button.Pressed, "#cancel")
    def cancel(self) -> None:
        """Cancel the find operation."""
        self.dismiss(None)

    @on(Button.Pressed, "#next")
    def find_next(self) -> None:
        """Find the next occurrence."""
        if term := self.query_one(Input).value:
            self.dismiss((term, True))

    @on(Button.Pressed, "#previous")
    def find_previous(self) -> None:
        """Find the previous occurrence."""
        if term := self.query_one(Input).value:
            self.dismiss((term, False))

    @on(Input.Submitted)
    def submit(self) -> None:
        """Submit the search (same as Next)."""
        if term := self.query_one(Input).value:
            self.dismiss((term, True))
