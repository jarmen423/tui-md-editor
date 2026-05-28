"""Provides the local files navigation pane."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from httpx import URL
from textual.app import ComposeResult
from textual.binding import Binding
from textual.message import Message
from textual.reactive import var
from textual.widgets import DirectoryTree

from .navigation_pane import NavigationPane


class FilteredDirectoryTree(DirectoryTree):  # pylint:disable=too-many-ancestors
    """A `DirectoryTree` filtered for the markdown viewer."""

    BINDINGS = [
        Binding("H", "toggle_hidden", "Toggle hidden files"),
    ]

    show_hidden: var[bool] = var(False)
    """Should hidden files be shown in the directory tree?"""

    def filter_paths(self, paths: Iterable[Path]) -> Iterable[Path]:
        """Filter the directory tree for the editor.

        Args:
            paths: The paths to be filtered.

        Returns:
            All non-hidden files and directories (or all files if
            ``show_hidden`` is ``True``).
        """
        try:
            if self.show_hidden:
                return list(paths)
            return [
                path
                for path in paths
                if not path.name.startswith(".")
            ]
        except PermissionError:
            return []

    def watch_show_hidden(self) -> None:
        """Reload the tree when the hidden-files toggle changes."""
        # Trigger the path watcher which properly reloads the tree.
        self.path = self.path

    def action_toggle_hidden(self) -> None:
        """Toggle the visibility of hidden files."""
        self.show_hidden = not self.show_hidden


class LocalFiles(NavigationPane):
    """Local file picking navigation pane."""

    DEFAULT_CSS = """
    LocalFiles {
        height: 100%;
    }

    LocalFiles > DirectoryTree {
        background: $panel;
        width: 1fr;
    }

    LocalFiles > DirectoryTree:focus .tree--cursor, LocalFiles > DirectoryTree .tree--cursor {
        background: $accent 50%;
        color: $text;
    }
    """

    def __init__(self) -> None:
        """Initialise the local files navigation pane."""
        super().__init__("Local")

    def compose(self) -> ComposeResult:
        """Compose the child widgets."""
        yield FilteredDirectoryTree(Path.cwd())

    def chdir(self, path: Path) -> None:
        """Change the filesystem view to the given directory.

        Args:
            path: The path to change to.
        """
        self.query_one(FilteredDirectoryTree).path = path

    def set_focus_within(self) -> None:
        """Focus the directory tree.."""
        self.query_one(DirectoryTree).focus(scroll_visible=False)

    class Goto(Message):
        """Message that requests the viewer goes to a given location."""

        def __init__(self, location: Path | URL) -> None:
            """Initialise the history goto message.

            Args:
                location: The location to go to.
            """
            super().__init__()
            self.location = location
            """The location to go to."""

    def on_directory_tree_file_selected(
        self, event: DirectoryTree.FileSelected
    ) -> None:
        """Handle a file being selected in the directory tree.

        Args:
            event: The direct tree selection event.
        """
        event.stop()
        self.post_message(self.Goto(Path(event.path)))
