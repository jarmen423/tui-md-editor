"""Tests for the live browser preview (``preview_server`` + omnibox wiring).

The preview serves the current document over localhost and pushes edits
to connected browsers via Server-Sent Events. Tests here cover the
rendering helpers, the standalone server (plain localhost HTTP, no
Textual needed), and the omnibox-to-screen command wiring.

Run with pytest from the project root:

    .venv-tui-md-editor\\Scripts\\pytest tests/test_preview_server.py -v
"""

from __future__ import annotations

import queue
import threading
import urllib.error
import urllib.request
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from tui_md_editor.app.app import MarkdownViewer
from tui_md_editor.screens.main import Main
from tui_md_editor.utility.html_export import (
    LIVE_RELOAD_SCRIPT,
    render_html_document,
    render_markdown_body,
)
from tui_md_editor.utility.preview_server import PreviewServer
from tui_md_editor.widgets.omnibox import Omnibox
from tui_md_editor.widgets.viewer import Viewer

SAMPLE = """---
title: Front matter is stripped
---

# Live Doc

Some `inline code` and prose.
"""


def _get(url: str, timeout: float = 10) -> str:
    """Fetch a URL and return the decoded body."""
    with urllib.request.urlopen(url, timeout=timeout) as response:
        assert response.status == 200
        return response.read().decode("utf-8")


@pytest.fixture(autouse=True)
def no_persisted_history() -> None:
    """Prevent tests from reading or writing real history on disk."""
    with (
        patch("tui_md_editor.screens.main.load_history", return_value=[]),
        patch("tui_md_editor.screens.main.save_history"),
    ):
        yield


class TestRenderMarkdownBody:
    def test_fragment_has_no_page_chrome(self) -> None:
        """Body fragment is inner HTML only, front matter stripped."""
        body = render_markdown_body(SAMPLE)
        assert "<h1>Live Doc</h1>" in body
        assert "Front matter is stripped" not in body
        assert "<html" not in body
        assert "<main>" not in body


class TestLiveReloadDocument:
    def test_static_export_has_no_live_script(self) -> None:
        """Default render is unchanged: no EventSource, no fetch."""
        page = render_html_document("t", SAMPLE)
        assert "EventSource" not in page
        assert "/events" not in page
        assert LIVE_RELOAD_SCRIPT not in page

    def test_live_reload_injects_scroll_preserving_script(self) -> None:
        """Live pages listen for events and swap <main> without jumping."""
        page = render_html_document("t", SAMPLE, live_reload=True)
        assert LIVE_RELOAD_SCRIPT in page
        assert 'new EventSource("/events")' in page
        assert 'fetch("/body"' in page
        assert "window.scrollY" in page
        assert "window.scrollTo(0, y)" in page


@pytest.fixture
def server() -> PreviewServer:
    """A started preview server, stopped after the test."""
    preview = PreviewServer("Doc", SAMPLE).start()
    assert preview.running
    yield preview
    preview.stop()
    assert not preview.running


class TestPreviewServer:
    def test_serves_full_live_page(self, server: PreviewServer) -> None:
        """GET / returns the styled page with the live script."""
        page = _get(server.url)
        assert "<title>Doc</title>" in page
        assert "<h1>Live Doc</h1>" in page
        assert LIVE_RELOAD_SCRIPT in page

    def test_serves_body_fragment(self, server: PreviewServer) -> None:
        """GET /body returns just the rendered fragment."""
        body = _get(server.url + "body")
        assert "<h1>Live Doc</h1>" in body
        assert "<html" not in body

    def test_unknown_path_is_404(self, server: PreviewServer) -> None:
        """Unknown routes return 404."""
        with pytest.raises(urllib.error.HTTPError) as excinfo:
            urllib.request.urlopen(server.url + "nope", timeout=10)
        assert excinfo.value.code == 404

    def test_binds_localhost_only(self, server: PreviewServer) -> None:
        """The preview never listens on an external interface."""
        assert server.url.startswith("http://127.0.0.1:")

    def test_update_changes_body(self, server: PreviewServer) -> None:
        """update() re-renders; identical updates are no-ops."""
        assert server.update("## Second", title="Doc", dark=True) is True
        assert "<h2>Second</h2>" in _get(server.url + "body")
        assert server.update("## Second", title="Doc", dark=True) is False

    def test_update_changes_title_and_theme(self, server: PreviewServer) -> None:
        """Title and palette follow update() too."""
        assert server.update(SAMPLE, title="Renamed", dark=False) is True
        page = _get(server.url)
        assert "<title>Renamed</title>" in page
        assert 'data-theme="light"' in page

    def test_events_stream_notifies_on_update(self, server: PreviewServer) -> None:
        """GET /events pushes a version line per update."""
        received: queue.Queue[str] = queue.Queue()

        def listen() -> None:
            seen = 0
            with urllib.request.urlopen(
                server.url + "events", timeout=15
            ) as response:
                while seen < 2:
                    line = response.readline().decode("utf-8").strip()
                    if line.startswith("data:"):
                        received.put(line)
                        seen += 1

        watcher = threading.Thread(target=listen, daemon=True)
        watcher.start()
        try:
            # Initial state arrives on connect...
            assert received.get(timeout=15).startswith("data:")
            # ...and each update pushes a new version.
            server.update("## Pushed", title="Doc", dark=True)
            assert received.get(timeout=15).startswith("data:")
        finally:
            watcher.join(timeout=15)

    def test_stop_releases_port(self) -> None:
        """After stop(), the port refuses connections."""
        preview = PreviewServer("t", "x").start()
        url = preview.url
        assert "<title>t</title>" in _get(url)
        preview.stop()
        with pytest.raises(urllib.error.URLError):
            urllib.request.urlopen(url, timeout=10)


def _patches() -> tuple:
    """Patches isolating app tests from disk config and real browsers."""
    return (
        patch(
            "tui_md_editor.screens.main.load_config",
            return_value=SimpleNamespace(light_mode=False),
        ),
        patch("tui_md_editor.screens.main.open_url"),
    )


class TestPreviewCommands:
    """End-to-end omnibox wiring: type a command, preview starts/stops."""

    @pytest.mark.asyncio
    async def test_preview_browser_starts_server(self) -> None:
        """`:preview browser` serves the current buffer and opens the URL."""
        app = MarkdownViewer(SimpleNamespace(file=[]))
        config_patch, browser_patch = _patches()
        with config_patch, browser_patch as mock_open:
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.pause()
                screen = app.screen
                viewer = screen.query_one(Viewer)
                viewer.editor.text = "# From Omnibox"
                omnibox = screen.query_one(Omnibox)
                omnibox.value = "preview browser"
                await omnibox.action_submit()
                await pilot.pause()
                await pilot.pause()
                try:
                    server = screen._preview_server
                    assert server is not None
                    assert server.running
                    mock_open.assert_called_once_with(server.url)
                    assert server.url.startswith("http://127.0.0.1:")
                    assert "<h1>From Omnibox</h1>" in _get(server.url + "body")
                finally:
                    if screen._preview_server is not None:
                        screen._preview_server.stop()
                        screen._preview_server = None

    @pytest.mark.asyncio
    async def test_colon_prefix_commands(self) -> None:
        """Commands accept a leading colon (``:preview stop``)."""
        app = MarkdownViewer(SimpleNamespace(file=[]))
        config_patch, browser_patch = _patches()
        with config_patch, browser_patch:
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.pause()
                screen = app.screen
                viewer = screen.query_one(Viewer)
                viewer.editor.text = "# Something"
                omnibox = screen.query_one(Omnibox)
                # Start with the bare command...
                omnibox.value = "preview browser"
                await omnibox.action_submit()
                await pilot.pause()
                await pilot.pause()
                assert screen._preview_server is not None
                # ...stop with the colon-prefixed command.
                omnibox.value = ":preview stop"
                await omnibox.action_submit()
                await pilot.pause()
                await pilot.pause()
                assert screen._preview_server is None

    @pytest.mark.asyncio
    async def test_commands_take_precedence_over_create(self) -> None:
        """A known command runs instead of prompting to create a file."""
        app = MarkdownViewer(SimpleNamespace(file=[]))
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.pause()
            screen = app.screen
            viewer = screen.query_one(Viewer)
            viewer.editor.text = "# Keep me"
            omnibox = screen.query_one(Omnibox)
            omnibox.value = "new"
            await omnibox.action_submit()
            await pilot.pause()
            await pilot.pause()
            # The `new` command ran (fresh untitled buffer)...
            assert viewer.editor.text == ""
            assert not viewer.viewing_location
            # ...rather than pushing a "Create file?" confirmation dialog.
            assert isinstance(app.screen, Main)

    @pytest.mark.asyncio
    async def test_content_change_pushes_to_browser(self) -> None:
        """Typing in the editor updates the served preview body."""
        app = MarkdownViewer(SimpleNamespace(file=[]))
        config_patch, browser_patch = _patches()
        with (
            config_patch,
            browser_patch,
            patch.object(Main, "_PREVIEW_DEBOUNCE", 0.01),
        ):
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.pause()
                screen = app.screen
                viewer = screen.query_one(Viewer)
                viewer.editor.text = "# First"
                omnibox = screen.query_one(Omnibox)
                omnibox.value = "preview browser"
                await omnibox.action_submit()
                await pilot.pause()
                await pilot.pause()
                try:
                    server = screen._preview_server
                    assert server is not None
                    assert "<h1>First</h1>" in _get(server.url + "body")
                    viewer.editor.text = "# Second"
                    await pilot.pause()
                    await pilot.pause()
                    await pilot.pause()
                    assert "<h1>Second</h1>" in _get(server.url + "body")
                finally:
                    if screen._preview_server is not None:
                        screen._preview_server.stop()
                        screen._preview_server = None
