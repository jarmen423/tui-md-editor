"""The markdown viewer and editor widget.

Extends Frogmouth's original viewer with an integrated TextArea editor,
enabling users to toggle between viewing rendered Markdown and editing
the raw source. Local files can be saved back to disk; remote URLs are
read-only.

Key Technologies/APIs:
    - :class:`textual.widgets.ContentSwitcher`
    - :class:`textual.widgets.TextArea`
    - :class:`textual.widgets.Markdown`
    - :class:`textual.containers.VerticalScroll`
"""

from __future__ import annotations

from collections import deque
from pathlib import Path
from typing import Callable
from webbrowser import open as open_url

from httpx import URL, AsyncClient, HTTPStatusError, RequestError
from markdown_it import MarkdownIt
from mdit_py_plugins import front_matter
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.message import Message
from textual.reactive import var
from textual.widgets import ContentSwitcher, Markdown, TextArea
from typing_extensions import Final

from .. import __version__
from ..dialogs import ErrorDialog
from ..utility.advertising import APPLICATION_TITLE, USER_AGENT

PLACEHOLDER = f"""\
# {APPLICATION_TITLE} {__version__}

Welcome to {APPLICATION_TITLE}!

Press **Ctrl+E** to edit the current document.
Press **Ctrl+S** to save your changes.
"""


class History:
    """Holds the browsing history for the viewer."""

    MAXIMUM_HISTORY_LENGTH: Final[int] = 256
    """The maximum number of items we'll keep in history."""

    def __init__(self, history: list[Path | URL] | None = None) -> None:
        """Initialise the history object."""
        self._history: deque[Path | URL] = deque(
            history or [], maxlen=self.MAXIMUM_HISTORY_LENGTH
        )
        """The list that holds the history of locations visited."""
        self._current: int = max(len(self._history) - 1, 0)
        """The current location."""

    @property
    def location(self) -> Path | URL | None:
        """The current location in the history."""
        try:
            return self._history[self._current]
        except IndexError:
            return None

    @property
    def current(self) -> int | None:
        """The current location in history, or None if there is no current location."""
        return None if self.location is None else self._current

    @property
    def locations(self) -> list[Path | URL]:
        """The locations in the history."""
        return list(self._history)

    def remember(self, location: Path | URL) -> None:
        """Remember a new location in the history.

        Args:
            location: The location to remember.
        """
        self._history.append(location)
        self._current = len(self._history) - 1

    def back(self) -> bool:
        """Go back in the history.

        Returns:
            `True` if the location changed, `False` if not.
        """
        if self._current:
            self._current -= 1
            return True
        return False

    def forward(self) -> bool:
        """Go forward in the history.

        Returns:
            `True` if the location changed, `False` if not.
        """
        if self._current < len(self._history) - 1:
            self._current += 1
            return True
        return False

    def __delitem__(self, index: int) -> None:
        del self._history[index]
        self._current = max(len(self._history) - 1, self._current)


class Viewer(VerticalScroll, can_focus=True, can_focus_children=True):
    """The markdown viewer and editor widget.

    Displays rendered Markdown by default. Pressing ``Ctrl+E`` toggles an
    embedded :class:`TextArea` for editing the raw source. Local files can
    be saved with ``Ctrl+S``; remote URLs are read-only.
    """

    DEFAULT_CSS = """
    Viewer {
        width: 1fr;
        scrollbar-gutter: stable;
    }

    /* In edit mode the TextArea fills the viewport. Remove its default
       border so we don't get a double-border effect with the Viewer's
       outer .focusable outline, and add a little horizontal padding. */
    Viewer TextArea {
        width: 100%;
        height: 100%;
        border: none;
        padding: 0 1;
    }
    """

    BINDINGS = [
        Binding("w,k", "scroll_up", "", show=False),
        Binding("s,j", "scroll_down", "", show=False),
        Binding("space", "page_down", "", show=False),
        Binding("b", "page_up", "", show=False),
    ]
    """Bindings for the Markdown viewer widget."""

    history: var[History] = var(History)
    """The browsing history."""

    viewing_location: var[bool] = var(False)
    """Is an actual location being viewed?"""

    edit_mode: var[bool] = var(False)
    """Is the widget currently in edit mode (showing the TextArea)?"""

    class ViewerMessage(Message):
        """Base class for viewer messages."""

        def __init__(self, viewer: Viewer) -> None:
            """Initialise the message.

            Args:
                viewer: The viewer sending the message.
            """
            super().__init__()
            self.viewer: Viewer = viewer
            """The viewer that sent the message."""

    class LocationChanged(ViewerMessage):
        """Message sent when the viewer location changes."""

    class HistoryUpdated(ViewerMessage):
        """Message sent when the history is updated."""

    class EditModeChanged(ViewerMessage):
        """Message sent when edit mode is toggled."""

    class DocumentSaved(ViewerMessage):
        """Message sent when a local document has been saved."""

    def compose(self) -> ComposeResult:
        """Compose the markdown viewer with embedded editor."""
        with ContentSwitcher(initial="markdown", id="viewer_switcher"):
            yield Markdown(
                PLACEHOLDER,
                id="markdown",
                parser_factory=lambda: MarkdownIt("gfm-like").use(
                    front_matter.front_matter_plugin
                ),
            )
            yield TextArea(id="editor", language="markdown")

    @property
    def document(self) -> Markdown:
        """The markdown document widget."""
        return self.query_one("#markdown", Markdown)

    @property
    def editor(self) -> TextArea:
        """The text area editor widget."""
        return self.query_one("#editor", TextArea)

    @property
    def switcher(self) -> ContentSwitcher:
        """The content switcher that toggles view/edit."""
        return self.query_one("#viewer_switcher", ContentSwitcher)

    @property
    def location(self) -> Path | URL | None:
        """The location that is currently being visited."""
        return self.history.location if self.viewing_location else None

    @property
    def is_dirty(self) -> bool:
        """Whether the editor buffer has unsaved changes."""
        return self._is_dirty

    @property
    def can_edit(self) -> bool:
        """Can the current location be edited?

        Only local :class:`Path` locations are editable; remote URLs are
        read-only.
        """
        return self.viewing_location and isinstance(self.location, Path)

    def __init__(self, *args, **kwargs) -> None:
        """Initialise the viewer and editor state."""
        super().__init__(*args, **kwargs)
        self._raw_content: str = ""
        self._is_dirty: bool = False

    def on_mount(self) -> None:
        """Post-mount: disable focus on Markdown children to avoid confusion."""
        self.document.can_focus_children = False

    def scroll_to_block(self, block_id: str) -> None:
        """Scroll the document to the given block ID.

        Args:
            block_id: The ID of the block to scroll to.
        """
        self.scroll_to_widget(self.document.query_one(f"#{block_id}"), top=True)

    def _post_load(self, location: Path | URL, remember: bool = True) -> None:
        """Perform some post-load tasks.

        Args:
            location: The location that has been loaded.
            remember: Should we remember the location in the history?
        """
        self.scroll_home(animate=False)
        self.viewing_location = True
        if remember:
            self.history.remember(location)
            self.post_message(self.HistoryUpdated(self))
        self.post_message(self.LocationChanged(self))
        # Force the VerticalScroll to recalculate its scroll region now
        # that the Markdown widget has fully rendered its content.
        self.refresh(layout=True)

    @work(exclusive=True)
    async def _local_load(self, location: Path, remember: bool = True) -> None:
        """Load a Markdown document from a local file.

        Reads the raw text into the editor and renders it in the Markdown
        widget.

        Args:
            location: The location to load from.
            remember: Should we remember the location in the history?
        """
        try:
            raw = location.read_text(encoding="utf-8")
            self._raw_content = raw
            self._is_dirty = False
            self.editor.text = raw
            await self.document.load(location)
        except OSError as error:
            self.app.push_screen(
                ErrorDialog(
                    "Error loading local document",
                    f"{location}\n\n{error}.",
                )
            )
        else:
            self._post_load(location, remember)

    @work(exclusive=True)
    async def _remote_load(self, location: URL, remember: bool = True) -> None:
        """Load a Markdown document from a URL.

        Args:
            location: The location to load from.
            remember: Should we remember the location in the history?
        """
        try:
            async with AsyncClient() as client:
                response = await client.get(
                    location,
                    follow_redirects=True,
                    headers={"user-agent": USER_AGENT},
                )
        except RequestError as error:
            self.app.push_screen(ErrorDialog("Error getting document", str(error)))
            return

        try:
            response.raise_for_status()
        except HTTPStatusError as error:
            self.app.push_screen(ErrorDialog("Error getting document", str(error)))
            return

        content_type = response.headers.get("content-type", "")
        if any(
            content_type.startswith(f"text/{sub_type}")
            for sub_type in ("plain", "markdown", "x-markdown")
        ):
            self._raw_content = response.text
            self._is_dirty = False
            self.editor.text = response.text
            self.document.update(response.text)
            self._post_load(location, remember)
        else:
            open_url(str(location))

    def visit(self, location: Path | URL, remember: bool = True) -> None:
        """Visit a location.

        Args:
            location: The location to visit.
            remember: Should this visit be added to the history?
        """
        # Exit edit mode when visiting a new location.
        if self.edit_mode:
            self.toggle_edit()

        if isinstance(location, Path):
            self._local_load(location.expanduser().resolve(), remember)
        elif isinstance(location, URL):
            self._remote_load(location, remember)
        else:
            raise ValueError("Unknown location type passed to the Markdown viewer")

    def reload(self) -> None:
        """Reload the current location."""
        if self.location is not None:
            self.visit(self.location, False)

    def show(self, content: str) -> None:
        """Show some direct text in the viewer.

        Args:
            content: The text to show.
        """
        self.viewing_location = False
        self._raw_content = content
        self._is_dirty = False
        self.editor.text = content
        self.document.update(content)
        self.scroll_home(animate=False)

    def toggle_edit(self) -> None:
        """Toggle between Markdown preview and TextArea edit mode.

        If the current location is a remote URL, shows a notification that
        the document is read-only.
        """
        if not self.viewing_location:
            self.app.notify("No document is currently open.", severity="warning")
            return

        if not self.can_edit:
            self.app.notify(
                "Remote documents are read-only.", severity="information"
            )
            return

        if self.edit_mode:
            # Switching from edit back to preview: refresh Markdown
            self.document.update(self.editor.text)
            self.switcher.styles.height = "auto"
            self.switcher.current = "markdown"
            self.edit_mode = False
            self.document.focus()
            # Ensure the VerticalScroll recalculates now that the Markdown
            # widget is visible again with its full content height.
            self.refresh(layout=True)
        else:
            # Switching from preview to edit
            self.switcher.styles.height = "100%"
            self.switcher.current = "editor"
            self.edit_mode = True
            self.editor.focus()

        self.post_message(self.EditModeChanged(self))

    def save_file(self) -> None:
        """Save the current editor buffer back to disk.

        Only works for local file paths. Shows a notification on success
        or failure.
        """
        if not self.can_edit:
            self.app.notify(
                "Nothing to save or document is read-only.", severity="warning"
            )
            return

        if not self._is_dirty:
            self.app.notify("No changes to save.", severity="information")
            return

        location = self.location
        assert isinstance(location, Path)
        try:
            location.write_text(self.editor.text, encoding="utf-8")
            self._raw_content = self.editor.text
            self._is_dirty = False
            self.app.notify("Saved successfully!", severity="information", timeout=2)
            self.post_message(self.DocumentSaved(self))
        except OSError as error:
            self.app.push_screen(
                ErrorDialog(
                    "Error saving document",
                    f"{location}\n\n{error}.",
                )
            )

    def on_text_area_changed(self) -> None:
        """Track dirty state when the user types in the editor."""
        if self.editor.text == self._raw_content:
            if self._is_dirty:
                self._is_dirty = False
        elif not self._is_dirty:
            self._is_dirty = True

    def _jump(self, direction: Callable[[], bool]) -> None:
        """Jump in a particular direction within the history.

        Args:
            direction: A function that jumps in the desired direction.
        """
        if direction():
            if self.history.location is not None:
                self.visit(self.history.location, remember=False)

    def back(self) -> None:
        """Go back in the viewer history."""
        self._jump(self.history.back)

    def forward(self) -> None:
        """Go forward in the viewer history."""
        self._jump(self.history.forward)

    def load_history(self, history: list[Path | URL]) -> None:
        """Load up a history list from the given history.

        Args:
            history: The history load up from.
        """
        self.history = History(history)
        self.post_message(self.HistoryUpdated(self))

    def delete_history(self, history_id: int) -> None:
        """Delete an item from the history.

        Args:
            history_id: The ID of the history item to delete.
        """
        try:
            del self.history[history_id]
        except IndexError:
            pass
        else:
            self.post_message(self.HistoryUpdated(self))

    def clear_history(self) -> None:
        """Clear down the whole of history."""
        self.load_history([])
