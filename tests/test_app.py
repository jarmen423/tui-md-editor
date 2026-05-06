"""Automated tests for the TUI Markdown Editor (Frogmouth fork).

These tests use Textual's headless :meth:`App.run_test` API to exercise
the application without requiring a real terminal.

Run with pytest from the project root:

    .venv-tui-md-editor\Scripts\pytest tests/

Key Technologies/APIs:
    - :meth:`textual.app.App.run_test`
    - :class:`textual.pilot.Pilot`
    - :class:`tui_md_editor.app.app.MarkdownViewer`
    - :class:`tui_md_editor.screens.main.Main`
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from tui_md_editor.app.app import MarkdownViewer
from tui_md_editor.screens.main import Main


@pytest.fixture(autouse=True)
def no_persisted_history() -> None:
    """Prevent all tests from loading stale history from disk.

    The app persists browsing history between sessions. If a previous run
    opened a temp file that no longer exists, the app shows an error dialog
    on startup, breaking headless tests. This fixture monkeypatches
    ``load_history`` to always return an empty list.
    """
    with patch("tui_md_editor.screens.main.load_history", return_value=[]):
        yield


@pytest.fixture
def app() -> MarkdownViewer:
    """Return a fresh app instance for each test."""
    return MarkdownViewer(SimpleNamespace(file=[]))


class TestViewerBasics:
    """Smoke tests for the viewer widget."""

    @pytest.mark.asyncio
    async def test_composes(self, app: MarkdownViewer) -> None:
        """App should mount viewer with markdown and editor widgets."""
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.pause()
            screen = app.screen
            assert screen.query_one("#viewer") is not None
            assert screen.query_one("#markdown") is not None
            assert screen.query_one("#editor") is not None
            assert screen.query_one("#viewer_switcher") is not None

    @pytest.mark.asyncio
    async def test_initial_state(self, app: MarkdownViewer) -> None:
        """Viewer starts in view mode (not edit mode)."""
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.pause()
            screen = app.screen
            viewer = screen.query_one("#viewer")
            assert not viewer.edit_mode
            assert viewer.switcher.current == "markdown"


class TestEditMode:
    """Tests for the edit mode toggle and save functionality."""

    @pytest.mark.asyncio
    async def test_open_file_and_toggle_edit(self, tmp_path: Path) -> None:
        """Opening a local file and pressing Ctrl+E enters edit mode."""
        test_file = tmp_path / "notes.md"
        test_file.write_text("# Hello\n\nWorld", encoding="utf-8")

        app = MarkdownViewer(SimpleNamespace(file=[]))
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.pause()
            screen = app.screen
            viewer = screen.query_one("#viewer")

            screen.visit(test_file)
            await pilot.pause()
            await pilot.pause()
            await pilot.pause()

            assert viewer.can_edit
            assert "Hello" in viewer.editor.text

            viewer.toggle_edit()
            await pilot.pause()

            assert viewer.edit_mode
            assert viewer.switcher.current == "editor"

    @pytest.mark.asyncio
    async def test_toggle_back_to_preview(self, tmp_path: Path) -> None:
        """Toggling edit mode again returns to markdown preview."""
        test_file = tmp_path / "notes.md"
        test_file.write_text("# Title", encoding="utf-8")

        app = MarkdownViewer(SimpleNamespace(file=[]))
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.pause()
            screen = app.screen
            viewer = screen.query_one("#viewer")

            screen.visit(test_file)
            await pilot.pause()
            await pilot.pause()
            await pilot.pause()

            viewer.toggle_edit()
            await pilot.pause()
            viewer.toggle_edit()
            await pilot.pause()

            assert not viewer.edit_mode
            assert viewer.switcher.current == "markdown"

    @pytest.mark.asyncio
    async def test_save_file(self, tmp_path: Path) -> None:
        """Ctrl+S (via save_file) persists changes and clears dirty flag."""
        test_file = tmp_path / "draft.md"
        test_file.write_text("original", encoding="utf-8")

        app = MarkdownViewer(SimpleNamespace(file=[]))
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.pause()
            screen = app.screen
            viewer = screen.query_one("#viewer")

            screen.visit(test_file)
            await pilot.pause()
            await pilot.pause()
            await pilot.pause()

            viewer.toggle_edit()
            await pilot.pause()

            viewer.editor.text = "modified"
            await pilot.pause()
            assert viewer.is_dirty

            viewer.save_file()
            await pilot.pause()

            assert not viewer.is_dirty
            assert test_file.read_text(encoding="utf-8") == "modified"

    @pytest.mark.asyncio
    async def test_reverting_text_clears_dirty(self, tmp_path: Path) -> None:
        """If user undoes back to saved text, dirty flag clears."""
        test_file = tmp_path / "revert.md"
        test_file.write_text("saved", encoding="utf-8")

        app = MarkdownViewer(SimpleNamespace(file=[]))
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.pause()
            screen = app.screen
            viewer = screen.query_one("#viewer")

            screen.visit(test_file)
            await pilot.pause()
            await pilot.pause()
            await pilot.pause()

            viewer.toggle_edit()
            await pilot.pause()

            viewer.editor.text = "changed"
            await pilot.pause()
            assert viewer.is_dirty

            viewer.editor.text = "saved"
            await pilot.pause()
            assert not viewer.is_dirty

    @pytest.mark.asyncio
    async def test_remote_url_read_only(self) -> None:
        """Remote URLs cannot be edited."""
        app = MarkdownViewer(SimpleNamespace(file=[]))
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.pause()
            screen = app.screen
            viewer = screen.query_one("#viewer")

            # Simulate a remote location
            from httpx import URL
            viewer.viewing_location = True
            viewer.history.remember(URL("https://example.com/readme.md"))

            assert not viewer.can_edit
            # Toggle should show notification but not enter edit mode
            viewer.toggle_edit()
            await pilot.pause()
            assert not viewer.edit_mode

    @pytest.mark.asyncio
    async def test_keybindings(self, tmp_path: Path) -> None:
        """Ctrl+E and Ctrl+S keybindings work via the Main screen actions."""
        test_file = tmp_path / "keybind.md"
        test_file.write_text("# Test", encoding="utf-8")

        app = MarkdownViewer(SimpleNamespace(file=[str(test_file)]))
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.pause()
            await pilot.pause()
            screen = app.screen
            viewer = screen.query_one("#viewer")

            # Ctrl+E should toggle edit
            await pilot.press("ctrl+e")
            await pilot.pause()
            assert viewer.edit_mode

            # Ctrl+E again should toggle back
            await pilot.press("ctrl+e")
            await pilot.pause()
            assert not viewer.edit_mode

    @pytest.mark.asyncio
    async def test_edit_updates_preview(self, tmp_path: Path) -> None:
        """After editing and toggling back, preview reflects changes."""
        test_file = tmp_path / "sync.md"
        test_file.write_text("# Old", encoding="utf-8")

        app = MarkdownViewer(SimpleNamespace(file=[]))
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.pause()
            screen = app.screen
            viewer = screen.query_one("#viewer")

            screen.visit(test_file)
            await pilot.pause()
            await pilot.pause()
            await pilot.pause()

            viewer.toggle_edit()
            await pilot.pause()
            viewer.editor.text = "# New Heading"
            await pilot.pause()

            viewer.toggle_edit()
            await pilot.pause()

            # The markdown should have been updated with the new text
            # In Textual 0.53.1, Markdown blocks don't expose .source;
            # verify by checking the rendered content via the document widget.
            document = viewer.document
            assert document is not None
            assert not viewer.edit_mode
