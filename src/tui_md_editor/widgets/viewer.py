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
from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.events import Key
from textual.message import Message
from textual.reactive import var
from textual.widgets import ContentSwitcher, Markdown, TextArea
from typing_extensions import Final

from .. import __version__
from ..dialogs import ErrorDialog, FindDialog, InputDialog
from ..utility.advertising import APPLICATION_TITLE, USER_AGENT
from ..utility.type_tests import is_text_file, language_for_path, maybe_markdown

def _welcome_text() -> str:
    """Generate a welcome screen with recent files from history."""
    from ..data.history import load_history

    history = load_history()
    lines = [
        f"# {APPLICATION_TITLE} {__version__}",
        "",
        "Welcome to the TUI Markdown Editor!",
        "",
        "| Key | Action |",
        "|-----|--------|",
        "| `/` or `:` | Focus the omnibox |",
        "| `Ctrl+E` | Toggle edit / preview |",
        "| `Ctrl+S` | Save changes |",
        "| `Ctrl+F` | Find in file |",
        "| `Ctrl+G` | Go to line |",
        "| `Ctrl+N` | New file |",
        "| `Ctrl+\\` | Split view |",
        "| `F1` | Help |",
        "",
    ]
    if history:
        lines.append("## Recent Files")
        lines.append("")
        for item in reversed(history[-10:]):
            path_str = str(item)
            lines.append(f"- `{path_str}`")
        lines.append("")
    return "\n".join(lines)


def _offset_to_location(text: str, offset: int) -> tuple[int, int]:
    """Convert a character offset into a (line, column) location.

    Args:
        text: The text to operate on.
        offset: The character offset (0-based).

    Returns:
        A (line, column) tuple.
    """
    line = 0
    col = 0
    for idx, ch in enumerate(text):
        if idx == offset:
            return (line, col)
        if ch == "\n":
            line += 1
            col = 0
        else:
            col += 1
    return (line, col)


class IndentingTextArea(TextArea):
    """A TextArea that handles Tab key for indentation and markdown formatting shortcuts."""

    def _wrap_selection(self, wrapper: str) -> None:
        """Wrap the current selection (or insert placeholders).

        Args:
            wrapper: The string to wrap around (e.g. '**').
        """
        start, end = self.selection
        if start != end:
            text = self.selected_text
            self.replace(f"{wrapper}{text}{wrapper}", start, end)
            # Place cursor after the wrapped text.
            new_end = (end[0], end[1] + len(wrapper) * 2)
            self.move_cursor(new_end)
        else:
            self.insert(f"{wrapper}{wrapper}")
            # Move cursor inside the wrappers.
            self.move_cursor_relative(columns=-len(wrapper))

    def _on_key(self, event: Key) -> None:
        """Handle key events for indentation and markdown formatting.

        Args:
            event: The key event to handle.
        """
        key = event.key
        if key == "tab":
            self.insert("    ")
            event.prevent_default()
            event.stop()
            return

        # Markdown formatting shortcuts (only when editing markdown).
        if getattr(self, "is_markdown_file", True):
            if key == "ctrl+b":
                self._wrap_selection("**")
                event.prevent_default()
                event.stop()
                return
            if key == "ctrl+i":
                self._wrap_selection("*")
                event.prevent_default()
                event.stop()
                return
            if key == "ctrl+k":
                self._wrap_selection("`")
                event.prevent_default()
                event.stop()
                return
            if key == "ctrl+shift+l":
                # Bullet list: insert '- ' at line start.
                row, _ = self.cursor_location
                lines = self.text.split("\n")
                if 0 <= row < len(lines):
                    lines[row] = "- " + lines[row]
                    self.text = "\n".join(lines)
                    self.move_cursor((row, 0))
                    self.move_cursor_relative(columns=2)
                event.prevent_default()
                event.stop()
                return
            if key == "ctrl+shift+o":
                # Ordered list: insert '1. ' at line start.
                row, _ = self.cursor_location
                lines = self.text.split("\n")
                if 0 <= row < len(lines):
                    lines[row] = "1. " + lines[row]
                    self.text = "\n".join(lines)
                    self.move_cursor((row, 0))
                    self.move_cursor_relative(columns=3)
                event.prevent_default()
                event.stop()
                return
            if key in ("ctrl+1", "ctrl+2", "ctrl+3", "ctrl+4", "ctrl+5", "ctrl+6"):
                level = int(key[-1])
                row, _ = self.cursor_location
                lines = self.text.split("\n")
                if 0 <= row < len(lines):
                    # Remove existing header markers if present.
                    stripped = lines[row].lstrip()
                    if stripped.startswith("#"):
                        stripped = stripped.lstrip("#").lstrip()
                    lines[row] = "#" * level + " " + stripped
                    self.text = "\n".join(lines)
                    self.move_cursor((row, 0))
                event.prevent_default()
                event.stop()
                return

        super()._on_key(event)


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

    Viewer #split {
        width: 100%;
        height: 100%;
    }

    Viewer #split_editor {
        width: 50%;
        height: 100%;
        border: none;
        padding: 0 1;
    }

    Viewer #split_markdown {
        width: 50%;
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

    is_plain_text: var[bool] = var(False)
    """Is the current document a plain text file (not Markdown)?"""

    split_mode: var[bool] = var(False)
    """Is the widget in split view (editor + preview side-by-side)?"""

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

    class CursorMoved(ViewerMessage):
        """Message sent when the editor cursor moves."""

    def compose(self) -> ComposeResult:
        """Compose the markdown viewer with embedded editor and split view."""
        welcome = _welcome_text()
        with ContentSwitcher(initial="markdown", id="viewer_switcher"):
            yield Markdown(
                welcome,
                id="markdown",
                parser_factory=lambda: MarkdownIt("gfm-like").use(
                    front_matter.front_matter_plugin
                ),
            )
            yield IndentingTextArea(id="editor", language="markdown")
            from textual.containers import Horizontal
            with Horizontal(id="split"):
                yield IndentingTextArea(id="split_editor", language="markdown")
                yield Markdown(
                    welcome,
                    id="split_markdown",
                    parser_factory=lambda: MarkdownIt("gfm-like").use(
                        front_matter.front_matter_plugin
                    ),
                )

    @property
    def document(self) -> Markdown:
        """The markdown document widget."""
        return self.query_one("#markdown", Markdown)

    @property
    def editor(self) -> IndentingTextArea:
        """The text area editor widget."""
        return self.query_one("#editor", IndentingTextArea)

    @property
    def split_editor(self) -> IndentingTextArea:
        """The text area in split view."""
        return self.query_one("#split_editor", IndentingTextArea)

    @property
    def split_markdown(self) -> Markdown:
        """The markdown widget in split view."""
        return self.query_one("#split_markdown", Markdown)

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

    @property
    def cursor_location(self) -> tuple[int, int]:
        """Current cursor location as (line, column)."""
        return self.editor.cursor_location

    @property
    def word_count(self) -> int:
        """Number of words in the current editor text."""
        return len(self.editor.text.split())

    def __init__(self, *args, **kwargs) -> None:
        """Initialise the viewer and editor state."""
        super().__init__(*args, **kwargs)
        self._raw_content: str = ""
        self._is_dirty: bool = False
        self._new_file_path: Path | None = None
        self._auto_save_timer = None

    def on_mount(self) -> None:
        """Post-mount: disable focus on Markdown children and start auto-save."""
        self.document.can_focus_children = False
        self.split_markdown.can_focus_children = False
        from ..data.config import load_config

        config = load_config()
        if config.auto_save:
            self._auto_save_timer = self.set_interval(
                config.auto_save_interval, self._auto_save
            )

    def _auto_save(self) -> None:
        """Auto-save the current document if dirty and editable."""
        if self._is_dirty and (self.can_edit or self._new_file_path is not None):
            self.save_file()

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
            self.is_plain_text = not maybe_markdown(location)
            lang = language_for_path(location)
            self.editor.language = lang
            self.editor.is_markdown_file = not self.is_plain_text
            if self.is_plain_text:
                # For plain text files, show the raw text in the markdown
                # widget too (it renders unformatted).
                self.document.update(raw)
            else:
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
            self.editor.language = "markdown"
            self.is_plain_text = not maybe_markdown(location)
            self.editor.is_markdown_file = not self.is_plain_text
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
        self.is_plain_text = False
        self._raw_content = content
        self._is_dirty = False
        self.editor.text = content
        self.editor.language = "markdown"
        self.editor.is_markdown_file = True
        self.document.update(content)
        self.scroll_home(animate=False)

    def new_file(self) -> None:
        """Open a new untitled buffer."""
        if self.edit_mode:
            self.toggle_edit()
        self.viewing_location = False
        self.is_plain_text = False
        self._raw_content = ""
        self._is_dirty = False
        self._new_file_path = None
        self.editor.text = ""
        self.editor.language = "markdown"
        self.editor.is_markdown_file = True
        self.document.update(_welcome_text())
        self.scroll_home(animate=False)
        self.post_message(self.LocationChanged(self))

    def toggle_edit(self) -> None:
        """Toggle between Markdown preview and TextArea edit mode.

        If the current location is a remote URL, shows a notification that
        the document is read-only.
        """
        if self.split_mode:
            self.toggle_split()
            return

        if not self.viewing_location and self._new_file_path is None:
            self.app.notify("No document is currently open.", severity="warning")
            return

        if not self.can_edit and self._new_file_path is None:
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

    def toggle_split(self) -> None:
        """Toggle split view (editor + preview side-by-side)."""
        if not self.viewing_location and self._new_file_path is None:
            self.app.notify("No document is currently open.", severity="warning")
            return

        if not self.can_edit and self._new_file_path is None:
            self.app.notify(
                "Remote documents are read-only.", severity="information"
            )
            return

        if self.split_mode:
            # Leaving split mode: copy text back to main editor
            self.editor.text = self.split_editor.text
            self.edit_mode = False
            self.split_mode = False
            self.switcher.styles.height = "auto"
            self.switcher.current = "markdown"
            self.document.update(self.editor.text)
            self.document.focus()
            self.refresh(layout=True)
        else:
            # Entering split mode: sync split editor and show it
            self.split_editor.text = self.editor.text
            self.split_editor.language = self.editor.language
            self.split_editor.is_markdown_file = self.editor.is_markdown_file
            self.split_markdown.update(self.editor.text)
            self.split_mode = True
            self.edit_mode = False
            self.switcher.styles.height = "100%"
            self.switcher.current = "split"
            self.split_editor.focus()

        self.post_message(self.EditModeChanged(self))

    def save_file(self) -> None:
        """Save the current editor buffer back to disk.

        Only works for local file paths. Shows a notification on success
        or failure.
        """
        if not self.can_edit and self._new_file_path is None:
            self.app.notify(
                "Nothing to save or document is read-only.", severity="warning"
            )
            return

        if not self._is_dirty:
            self.app.notify("No changes to save.", severity="information")
            return

        location = self.location
        if location is None and self._new_file_path is not None:
            location = self._new_file_path

        if location is None:
            # Untitled buffer — prompt for path via callback.
            self.app.push_screen(
                InputDialog("Save as:", str(Path.cwd() / "untitled.md")),
                self._do_save,
            )
            return

        self._do_save(location)

    def _do_save(self, location: Path | str | None) -> None:
        """Perform the actual save operation.

        Args:
            location: The path to save to. May be a string from the dialog.
        """
        if location is None:
            return
        path = Path(location).expanduser().resolve()
        try:
            path.write_text(self.editor.text, encoding="utf-8")
            self._raw_content = self.editor.text
            self._is_dirty = False
            self._new_file_path = None
            self.app.notify("Saved successfully!", severity="information", timeout=2)
            self.post_message(self.DocumentSaved(self))
            # If this was an untitled buffer, convert it into a real visit.
            if self.location != path:
                self.visit(path)
        except OSError as error:
            self.app.push_screen(
                ErrorDialog(
                    "Error saving document",
                    f"{path}\n\n{error}.",
                )
            )

    @on(TextArea.Changed, "#editor")
    def on_editor_changed(self) -> None:
        """Track dirty state and sync split view when the main editor types."""
        if self.editor.text == self._raw_content:
            if self._is_dirty:
                self._is_dirty = False
        elif not self._is_dirty:
            self._is_dirty = True
        self.post_message(self.CursorMoved(self))

    @on(TextArea.Changed, "#split_editor")
    def on_split_editor_changed(self) -> None:
        """Track dirty state and sync markdown when the split editor types."""
        if self.split_editor.text == self._raw_content:
            if self._is_dirty:
                self._is_dirty = False
        elif not self._is_dirty:
            self._is_dirty = True
        if self.split_mode:
            self.split_markdown.update(self.split_editor.text)
        self.post_message(self.CursorMoved(self))

    def on_text_area_selection_changed(self) -> None:
        """Notify that the cursor has moved."""
        self.post_message(self.CursorMoved(self))

    def find_text(self, term: str, forward: bool = True) -> bool:
        """Find the next occurrence of ``term`` in the editor.

        Args:
            term: The text to search for.
            forward: Search forward (``True``) or backward (``False``).

        Returns:
            ``True`` if a match was found and cursor moved.
        """
        if not term:
            return False
        text = self.editor.text
        cursor = self.editor.cursor_location
        # Convert cursor location to a character offset.
        lines = text.split("\n")
        offset = sum(len(lines[i]) + 1 for i in range(cursor[0])) + cursor[1]

        if forward:
            pos = text.find(term, offset + 1)
            if pos == -1:
                pos = text.find(term, 0)
        else:
            pos = text.rfind(term, 0, offset)
            if pos == -1:
                pos = text.rfind(term)

        if pos == -1:
            self.app.notify("No matches found.", severity="warning")
            return False

        loc = _offset_to_location(text, pos)
        self.editor.move_cursor(loc, center=True)
        return True

    def action_find(self) -> None:
        """Open the find dialog and jump to the first match."""
        if not self.edit_mode:
            self.toggle_edit()

        def on_result(result: tuple[str, bool] | None) -> None:
            if result is not None:
                term, forward = result
                self.find_text(term, forward)

        self.app.push_screen(FindDialog(), on_result)

    def toggle_wrap(self) -> None:
        """Toggle soft word wrap in the editor."""
        self.editor.soft_wrap = not self.editor.soft_wrap
        state = "on" if self.editor.soft_wrap else "off"
        self.app.notify(f"Word wrap {state}.", severity="information", timeout=1)

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
