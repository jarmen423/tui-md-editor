"""Tests for the styled HTML export (``tui_md_editor.utility.html_export``)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from tui_md_editor.app.app import MarkdownViewer
from tui_md_editor.utility.html_export import GEIST_FONTS_URL, render_html_document
from tui_md_editor.widgets.omnibox import Omnibox
from tui_md_editor.widgets.viewer import Viewer

SAMPLE = """---
title: Front matter is stripped
---

# Hello

Some `inline code` and prose.

```python
print("fenced")
```
"""


class TestRenderHtmlDocument:
    def test_complete_document_structure(self) -> None:
        """Output is a standalone page with title, fonts, and body."""
        page = render_html_document("My Doc", SAMPLE)
        assert page.startswith("<!DOCTYPE html>")
        assert "<title>My Doc</title>" in page
        assert GEIST_FONTS_URL in page
        assert "<h1>Hello</h1>" in page
        assert "Front matter is stripped" not in page

    def test_prose_uses_geist_sans_code_uses_mono(self) -> None:
        """Body font stack leads with Geist Sans; code with Geist Mono."""
        page = render_html_document("t", SAMPLE)
        assert '"Geist Sans", "Geist"' in page
        assert "font-family" in page
        # The mono stack must exist and apply to code elements.
        assert '"Geist Mono", ui-monospace' in page
        assert "<code" in page

    def test_title_is_escaped(self) -> None:
        """Titles can't break out of <title>."""
        page = render_html_document("<script>alert(1)</script>", "x")
        assert "<script>" not in page
        assert "&lt;script&gt;" in page

    def test_dark_palette_by_default(self) -> None:
        """Default export is dark like the T3-style reading aesthetic."""
        page = render_html_document("t", "x")
        assert 'data-theme="dark"' in page
        assert "#0a0a0a" in page

    def test_light_palette_opt_in(self) -> None:
        """Light mode follows the app theme instead."""
        page = render_html_document("t", "x", dark=False)
        assert 'data-theme="light"' in page
        assert "#0a0a0a" not in page
        assert "#ffffff" in page


class TestExportHtmlCommand:
    """The omnibox export command writes a complete styled page."""

    @pytest.mark.asyncio
    async def test_handler_writes_styled_document(self, tmp_path: Path) -> None:
        """Posting ExportHtmlCommand writes Geist-styled HTML to target."""
        target = tmp_path / "out.html"
        app = MarkdownViewer(SimpleNamespace(file=[]))
        with (
            patch("tui_md_editor.screens.main.load_history", return_value=[]),
            patch("tui_md_editor.screens.main.save_history"),
            patch(
                "tui_md_editor.screens.main.load_config",
                return_value=SimpleNamespace(light_mode=False),
            ),
        ):
            async with app.run_test() as pilot:
                await pilot.pause()
                viewer = app.screen.query_one(Viewer)
                viewer.editor.text = "# Exported\n\nHello `code`."
                app.screen.post_message(Omnibox.ExportHtmlCommand(target))
                await pilot.pause()
                await pilot.pause()
        written = target.read_text(encoding="utf-8")
        assert written.startswith("<!DOCTYPE html>")
        assert "<h1>Exported</h1>" in written
        assert GEIST_FONTS_URL in written
        assert '"Geist Mono", ui-monospace' in written
        assert 'data-theme="dark"' in written
