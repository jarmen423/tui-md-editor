"""Status bar widget for the viewer."""

from __future__ import annotations

from pathlib import Path

from httpx import URL
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.reactive import reactive
from textual.widgets import Static


class StatusBar(Horizontal):
    """A status bar showing file info, cursor position, and word count."""

    DEFAULT_CSS = """
    StatusBar {
        dock: bottom;
        height: 1;
        background: $surface;
        color: $text;
        padding: 0 1;
    }

    StatusBar Static {
        width: auto;
        content-align: center middle;
    }

    StatusBar #status-left {
        width: 1fr;
        content-align: left middle;
    }

    StatusBar #status-center {
        width: 1fr;
        content-align: center middle;
    }

    StatusBar #status-right {
        width: 1fr;
        content-align: right middle;
    }
    """

    file_name: reactive[str] = reactive("Untitled")
    dirty: reactive[bool] = reactive(False)
    file_type: reactive[str] = reactive("")
    line: reactive[int] = reactive(0)
    column: reactive[int] = reactive(0)
    words: reactive[int] = reactive(0)

    def compose(self) -> ComposeResult:
        """Compose the status bar widgets."""
        yield Static("", id="status-left")
        yield Static("", id="status-center")
        yield Static("", id="status-right")

    def watch_file_name(self) -> None:
        """Update left panel when filename changes."""
        self._update_left()

    def watch_dirty(self) -> None:
        """Update left panel when dirty state changes."""
        self._update_left()

    def _update_left(self) -> None:
        """Render the left panel."""
        dirty_mark = " [*]" if self.dirty else ""
        self.query_one("#status-left", Static).update(f"{self.file_name}{dirty_mark}")

    def watch_file_type(self) -> None:
        """Update center panel when file type changes."""
        self.query_one("#status-center", Static).update(self.file_type)

    def watch_line(self) -> None:
        """Update right panel when cursor moves."""
        self._update_right()

    def watch_column(self) -> None:
        """Update right panel when cursor moves."""
        self._update_right()

    def watch_words(self) -> None:
        """Update right panel when word count changes."""
        self._update_right()

    def _update_right(self) -> None:
        """Render the right panel."""
        self.query_one("#status-right", Static).update(
            f"Ln {self.line + 1}, Col {self.column + 1}    Words: {self.words}"
        )
