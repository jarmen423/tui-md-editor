"""Tests for the Typst-based typeset preview.

Covers the Markdown to Typst conversion, that converted documents actually
compile, the compile worker round trip, and toggling the preview in the app.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from tui_md_editor.app.app import MarkdownViewer
from tui_md_editor.utility.typeset import (
    DARK_PALETTE,
    LIGHT_PALETTE,
    TYPST_AVAILABLE,
    TypesetError,
    TypesetRenderer,
    build_document,
    code_to_typst,
    markdown_to_typst,
    page_ppi,
    typst_root,
)
from tui_md_editor.widgets.typeset_preview import TYPESET_AVAILABLE, TypesetPreview

needs_typst = pytest.mark.skipif(not TYPST_AVAILABLE, reason="typst not installed")

SAMPLE = """\
---
title: hidden
---
# Title

Text with **bold**, *em*, ~~gone~~, `code`, [a link](https://example.com),
$5 #tag @who a_b*c [x] 1. "quotes".

- one
  - nested
- [ ] todo
- [x] done

3. three
4. four

> quoted

```python
print("hi")
```

| L | C | R |
|:--|:-:|--:|
| a | b |
"""


def _compile(document: str, root: str) -> bytes:
    """Compile a document in-process, as the worker would."""
    import typst

    return typst.compile(document.encode("utf-8"), root=root, format="png", ppi=96)


class TestMarkdownToTypst:
    """Tests for the Markdown to Typst converter."""

    def test_markup_characters_are_escaped(self) -> None:
        """Text that looks like Typst markup is escaped, quotes are kept."""
        body = markdown_to_typst('$5 #tag @who a_b [x] "q"', None)
        assert r"\$5 \#tag \@who a\_b \[x\]" in body
        assert '"q"' in body

    def test_paragraph_start_cannot_become_a_list(self) -> None:
        """An escaped Markdown list marker stays literal text."""
        assert markdown_to_typst(r"1\. not a list", None) == r"1\. not a list"

    def test_front_matter_is_dropped(self) -> None:
        """YAML front matter isn't typeset."""
        assert "hidden" not in markdown_to_typst(SAMPLE, None)

    def test_structure(self) -> None:
        """Headings, lists, tasks, quotes, code and tables convert."""
        body = markdown_to_typst(SAMPLE, None)
        assert "#heading(level: 1)[Title];" in body
        assert "#strong[bold];" in body
        assert "#strike[gone];" in body
        assert '#link("https://example.com")[a link];' in body
        assert "#md-task(false);" in body
        assert "#md-task(true);" in body
        assert "#enum(tight: true, start: 3," in body
        assert "#quote(block: true)[quoted];" in body
        assert '#raw(block: true, lang: "python", "print(\\"hi\\")");' in body
        assert "align: (left, center, right,)" in body

    def test_missing_and_remote_images_fall_back_to_alt_text(self, tmp_path: Path) -> None:
        """Images that can't be embedded show their alt text."""
        body = markdown_to_typst("![gone](nope.png) ![web](https://x.test/a.png)", tmp_path)
        assert "md-image" not in body
        assert r"\[gone\]" in body and r"\[web\]" in body

    def test_local_image_is_rooted_at_the_drive(self, tmp_path: Path) -> None:
        """Local images are referenced relative to the Typst root."""
        (tmp_path / "pic.png").write_bytes(b"")
        body = markdown_to_typst("![pic](pic.png)", tmp_path)
        rooted = "/" + (tmp_path / "pic.png").resolve().relative_to(tmp_path.anchor).as_posix()
        assert f'#md-image("{rooted}");' in body


@needs_typst
class TestBuildDocument:
    """Tests that converted documents compile with Typst."""

    @pytest.mark.parametrize("palette", [DARK_PALETTE, LIGHT_PALETTE])
    def test_sample_compiles(self, palette, tmp_path: Path) -> None:
        """The sample document typesets to a PNG of the requested width."""
        body = markdown_to_typst(SAMPLE, tmp_path)
        png = _compile(build_document(body, 800, 96, palette), typst_root(tmp_path))
        assert png.startswith(b"\x89PNG")
        assert int.from_bytes(png[16:20], "big") == 800

    def test_code_file_compiles(self, tmp_path: Path) -> None:
        """Non-Markdown files typeset as one highlighted block."""
        body = code_to_typst('{"a": [1, 2]}\n', "json")
        png = _compile(build_document(body, 600, 96, DARK_PALETTE), typst_root(tmp_path))
        assert png.startswith(b"\x89PNG")

    def test_ppi_tracks_cell_width(self) -> None:
        """Wider terminal cells render at a higher resolution."""
        assert page_ppi(12) > page_ppi(9)


@needs_typst
class TestTypesetRenderer:
    """Tests for the compile worker process."""

    @pytest.mark.asyncio
    async def test_round_trip_and_errors(self, tmp_path: Path) -> None:
        """The worker returns PNGs, reports errors, and keeps working."""
        renderer = TypesetRenderer()
        try:
            document = build_document("Hello", 400, 96, LIGHT_PALETTE)
            root = typst_root(tmp_path)
            png = await renderer.render(document, root, 96)
            assert png.startswith(b"\x89PNG")

            with pytest.raises(TypesetError):
                await renderer.render("#nonexistent-function()", root, 96)

            assert (await renderer.render(document, root, 96)).startswith(b"\x89PNG")
        finally:
            await renderer.shutdown()


@pytest.mark.skipif(not TYPESET_AVAILABLE, reason="typeset preview unavailable")
class TestTypesetToggle:
    """Tests for toggling the typeset preview in the app."""

    @staticmethod
    async def _wait_for_tiles(preview: TypesetPreview) -> int:
        """Wait (up to 20s, for a cold font scan) for strips to appear."""
        for _ in range(200):
            if tiles := len(preview.query(".typeset-tile")):
                return tiles
            await asyncio.sleep(0.1)
        return 0

    @pytest.mark.asyncio
    async def test_alt_p_shows_typeset_page(self, tmp_path: Path) -> None:
        """Alt+P swaps the text preview for typeset strips, and back."""
        doc = tmp_path / "doc.md"
        doc.write_text("# Hello\n\nSome *text*.", encoding="utf-8")

        app = MarkdownViewer(SimpleNamespace(file=[str(doc)]))
        async with app.run_test() as pilot:
            for _ in range(3):
                await pilot.pause()
            viewer = app.screen.query_one("#viewer")

            await pilot.press("alt+p")
            await pilot.pause()
            assert viewer.switcher.current == "typeset"
            assert await self._wait_for_tiles(app.screen.query_one("#typeset", TypesetPreview))

            await pilot.press("alt+p")
            await pilot.pause()
            assert viewer.switcher.current == "markdown"

    @pytest.mark.asyncio
    async def test_split_view_uses_typeset_pane(self, tmp_path: Path) -> None:
        """In split view the typeset pane replaces the text preview."""
        doc = tmp_path / "split.md"
        doc.write_text("# Split", encoding="utf-8")

        app = MarkdownViewer(SimpleNamespace(file=[str(doc)]))
        async with app.run_test() as pilot:
            for _ in range(3):
                await pilot.pause()
            await pilot.press("alt+p")
            await pilot.press("ctrl+backslash")
            await pilot.pause()

            split_typeset = app.screen.query_one("#split_typeset", TypesetPreview)
            assert split_typeset.display is True
            assert app.screen.query_one("#split_markdown").display is False
            assert await self._wait_for_tiles(split_typeset)
