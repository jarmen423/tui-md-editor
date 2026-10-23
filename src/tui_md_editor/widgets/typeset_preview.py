"""In-terminal typeset preview, drawn with terminal graphics.

The document is typeset by :mod:`tui_md_editor.utility.typeset` into one
tall image sized to the pane, then cut into strips a few rows high. Each
strip is its own image widget so that, with Sixel, scrolling only
re-encodes the strips cut by the top and bottom edges, and an edit only
redraws the strips whose pixels actually changed.

Importing this module probes the terminal for Sixel / kitty graphics
support (via ``textual_image.widget``); that has to happen before Textual
takes over the terminal, which is why the viewer imports it at load time.

Key Technologies/APIs:
    - :mod:`textual_image.widget` (Sixel, kitty TGP, half-cell fallback)
    - :class:`PIL.Image.Image`
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

from textual import work
from textual.containers import VerticalScroll
from textual.widgets import Static

from ..utility.typeset import (
    DARK_PALETTE,
    LIGHT_PALETTE,
    TYPST_AVAILABLE,
    TypesetError,
    TypesetPalette,
    build_document,
    code_to_typst,
    markdown_to_typst,
    page_ppi,
    renderer,
    typst_root,
)

try:
    from PIL import Image as PILImage
    from textual_image._terminal import get_cell_size
    from textual_image.renderable import Image as _BestRenderable
    from textual_image.renderable.halfcell import Image as _HalfcellRenderable
    from textual_image.renderable.unicode import Image as _UnicodeRenderable
    from textual_image.widget import Image as GraphicsImage
except ImportError:  # pragma: no cover - only on Python < 3.12
    TYPESET_AVAILABLE = False
    HAS_TERMINAL_GRAPHICS = False
else:
    TYPESET_AVAILABLE = TYPST_AVAILABLE
    HAS_TERMINAL_GRAPHICS = _BestRenderable not in (_HalfcellRenderable, _UnicodeRenderable)

TILE_ROWS = 6
"""Height of each image strip, in terminal rows."""


class TypesetPreview(VerticalScroll, can_focus=False):
    """A typeset rendering of a Markdown document."""

    DEFAULT_CSS = """
    TypesetPreview {
        height: auto;
        padding: 0;
        scrollbar-gutter: stable;
    }

    TypesetPreview > .typeset-tile {
        width: auto;
        height: auto;
        margin: 0;
        padding: 0;
    }

    TypesetPreview > #typeset-status {
        color: $text-muted;
        padding: 1 2;
    }
    """

    _DEBOUNCE: float = 0.15
    """Delay in seconds before re-typesetting after a change."""

    def __init__(self, *args, **kwargs) -> None:
        """Initialise the preview."""
        super().__init__(*args, **kwargs)
        self._source: tuple[str, Path | None, str | None] | None = None
        """The text, its directory, and the code language (``None`` for Markdown)."""
        self._rendered_key: tuple | None = None
        """Inputs of the image currently on screen, to skip identical renders."""
        self._timer = None
        """Pending debounced render."""
        self._tiles: list[PILImage.Image] = []
        """Pixel data of each strip currently shown."""

    def compose(self):
        """Compose the preview with its status line."""
        yield Static("Typesetting…", id="typeset-status")

    def on_mount(self) -> None:
        """Re-typeset when the theme changes."""
        self.app.theme_changed_signal.subscribe(self, lambda _: self._schedule())

    def on_resize(self) -> None:
        """Re-typeset to the new width."""
        self._schedule()

    def set_source(self, text: str, base_dir: Path | None, language: str | None = None) -> None:
        """Set the document to typeset.

        Args:
            text: The document text.
            base_dir: Directory that relative image paths resolve against.
            language: Code language for non-Markdown files, else ``None``.
        """
        self._source = (text, base_dir, language)
        self._schedule()

    def _schedule(self) -> None:
        """Debounce a render."""
        if self._source is None or not self.display:
            return
        if self._timer is not None:
            self._timer.stop()
        self._timer = self.set_timer(self._DEBOUNCE, self._typeset)

    def _palette(self) -> TypesetPalette:
        """Pick page colours that blend with the current theme."""
        base = DARK_PALETTE if self.app.current_theme.dark else LIGHT_PALETTE
        _, background = self.background_colors
        return TypesetPalette(
            background=background.hex6,
            foreground=base.foreground,
            muted=base.muted,
            border=base.border,
            code_background=base.code_background,
            accent=base.accent,
            dark=base.dark,
        )

    @work(exclusive=True, group="typeset")
    async def _typeset(self) -> None:
        """Typeset the source and show it as image strips."""
        if self._source is None:
            return
        columns = self.scrollable_content_region.width
        if columns <= 0:
            return
        text, base_dir, language = self._source
        cell = get_cell_size()
        width_px = columns * cell.width
        ppi = page_ppi(cell.width)
        palette = self._palette()
        key = (text, base_dir, language, width_px, cell, palette)
        if key == self._rendered_key:
            return

        def document(images: bool) -> str:
            body = (
                code_to_typst(text, language)
                if language is not None
                else markdown_to_typst(text, base_dir, images=images)
            )
            return build_document(body, width_px, ppi, palette)

        root = typst_root(base_dir)
        try:
            try:
                png = await renderer.render(document(images=True), root, ppi)
            except TypesetError:
                # Most often an image Typst can't decode; retry without them.
                png = await renderer.render(document(images=False), root, ppi)
        except TypesetError as error:
            self._show_status(f"Couldn't typeset this document:\n\n{error}")
            self._rendered_key = None
            return

        self._show_tiles(self._slice(png, width_px, cell.height, palette), columns)
        self._rendered_key = key

    @staticmethod
    def _slice(png: bytes, width_px: int, cell_height: int, palette: TypesetPalette) -> list:
        """Cut the page into strips exactly ``TILE_ROWS`` cells high.

        Strips are padded to whole cells so the terminal draws them without
        rescaling.

        Args:
            png: The rendered page.
            width_px: The pane width in pixels.
            cell_height: Height of a terminal cell in pixels.
            palette: Page colours, for padding.

        Returns:
            The strips, top to bottom.
        """
        page = PILImage.open(BytesIO(png)).convert("RGB")
        tile_px = TILE_ROWS * cell_height
        height = -(-page.height // tile_px) * tile_px
        canvas = PILImage.new("RGB", (width_px, height), palette.background)
        canvas.paste(page.crop((0, 0, min(page.width, width_px), page.height)))
        return [canvas.crop((0, top, width_px, top + tile_px)) for top in range(0, height, tile_px)]

    def _show_status(self, message: str) -> None:
        """Replace the page with a status message.

        Args:
            message: The message to show.
        """
        self.query(".typeset-tile").remove()
        self._tiles = []
        status = self.query_one("#typeset-status", Static)
        status.update(message)
        status.display = True

    def _show_tiles(self, tiles: list, columns: int) -> None:
        """Show new strips, only touching the ones that changed.

        Args:
            tiles: The new strips, top to bottom.
            columns: Width of the pane in cells.
        """
        self.query_one("#typeset-status", Static).display = False
        widgets = list(self.query(".typeset-tile").results(GraphicsImage))
        for index, tile in enumerate(tiles):
            if index < len(widgets):
                widget = widgets[index]
                if widget.styles.width.value != columns:
                    widget.styles.width = columns
                elif index < len(self._tiles) and self._tiles[index].tobytes() == tile.tobytes():
                    continue
                widget.image = tile
            else:
                widget = GraphicsImage(tile, classes="typeset-tile")
                widget.styles.width = columns
                widget.styles.height = TILE_ROWS
                self.mount(widget)
        for widget in widgets[len(tiles) :]:
            widget.remove()
        self._tiles = tiles
