"""Typeset Markdown into page images with Typst.

Powers the in-terminal typeset preview (see
:mod:`tui_md_editor.widgets.typeset_preview`). Markdown is parsed with the
same ``gfm-like`` markdown-it parser the rest of the app uses, converted to
Typst markup, and compiled to a single tall PNG that the terminal can show
with Sixel or the kitty graphics protocol.

Compilation runs in a dedicated worker process
(:mod:`tui_md_editor.utility.typeset_worker`): Typst holds the GIL while it
compiles (and the first compile scans every system font, which takes around
a second), so compiling in-process would freeze the UI.

Key Technologies/APIs:
    - :mod:`typst` (Typst compiler bindings)
    - :class:`markdown_it.tree.SyntaxTreeNode`
    - :func:`asyncio.create_subprocess_exec`
"""

from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from markdown_it import MarkdownIt
from markdown_it.tree import SyntaxTreeNode
from mdit_py_plugins import front_matter

try:
    import typst  # noqa: F401  # pylint: disable=unused-import
except ImportError:  # pragma: no cover - only on Python < 3.12
    TYPST_AVAILABLE = False
else:
    TYPST_AVAILABLE = True


_SANS_FONTS = (
    "Geist",
    "Inter",
    "Segoe UI",
    "SF Pro Text",
    "Helvetica Neue",
    "Noto Sans",
    "DejaVu Sans",
    "Libertinus Serif",
)
"""Body font preference, mirroring the HTML export's sans stack."""

_MONO_FONTS = (
    "Geist Mono",
    "Cascadia Code",
    "Cascadia Mono",
    "JetBrains Mono",
    "SF Mono",
    "Menlo",
    "Consolas",
    "DejaVu Sans Mono",
)
"""Code font preference, mirroring the HTML export's mono stack."""

_IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp"})
"""Image formats Typst can embed."""

_ESCAPED = frozenset("\\*_`$#[]<>@=-+/~{}^.:")
"""Characters with markup meaning in Typst that must be backslash-escaped.

Quotes are deliberately left alone so Typst turns them into smart quotes.
"""

BODY_SIZE_PT = 11.0
"""Body text size; the preview is scaled so this matches the terminal font."""

MAX_MEASURE_PT = 520.0
"""Widest text column, so lines stay readable in wide terminals."""


@dataclass(frozen=True)
class TypesetPalette:
    """Colours for a typeset page, as ``#rrggbb`` strings."""

    background: str
    foreground: str
    muted: str
    border: str
    code_background: str
    accent: str
    dark: bool


DARK_PALETTE = TypesetPalette(
    background="#0a0a0a",
    foreground="#ededed",
    muted="#a1a1a1",
    border="#2e2e2e",
    code_background="#161616",
    accent="#4493f8",
    dark=True,
)
"""Dark palette, matching the HTML export."""

LIGHT_PALETTE = TypesetPalette(
    background="#ffffff",
    foreground="#171717",
    muted="#666666",
    border="#e5e5e5",
    code_background="#f4f4f5",
    accent="#0070f3",
    dark=False,
)
"""Light palette, matching the HTML export."""


def _dark_code_theme() -> str:
    """Build a small TextMate theme for code blocks on dark backgrounds.

    Typst's built-in highlighting theme assumes a light page.

    Returns:
        The theme as a ``.tmTheme`` plist document.
    """
    scopes = (
        ("comment", "#8b949e", "italic"),
        ("string", "#a5d6ff", ""),
        ("constant.numeric, constant.language, constant.character", "#79c0ff", ""),
        ("keyword, storage, storage.type", "#ff7b72", ""),
        ("entity.name.function, support.function", "#d2a8ff", ""),
        ("entity.name.type, entity.name.class, support.type, support.class", "#ffa657", ""),
        ("entity.name.tag", "#7ee787", ""),
        ("entity.other.attribute-name, variable.parameter", "#79c0ff", ""),
        ("markup.heading", "#79c0ff", "bold"),
    )
    rules = "".join(
        "<dict><key>scope</key><string>{0}</string><key>settings</key><dict>"
        "<key>foreground</key><string>{1}</string>"
        "<key>fontStyle</key><string>{2}</string></dict></dict>".format(*scope)
        for scope in scopes
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?><plist version="1.0"><dict>'
        "<key>name</key><string>tui-md-editor dark</string>"
        "<key>settings</key><array><dict><key>settings</key><dict>"
        "<key>foreground</key><string>#e6edf3</string></dict></dict>"
        f"{rules}</array></dict></plist>"
    )


def _string(value: str) -> str:
    """Quote a value as a Typst string literal.

    Args:
        value: The raw string.

    Returns:
        The Typst string literal, quotes included.
    """
    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\r", "")
        .replace("\n", "\\n")
        .replace("\t", "\\t")
    )
    return f'"{escaped}"'


def _escape(text: str) -> str:
    """Escape plain text for Typst markup.

    Args:
        text: The text to escape.

    Returns:
        The text with markup characters escaped and newlines flattened.
    """
    return "".join(f"\\{char}" if char in _ESCAPED else char for char in text).replace(
        "\n", " "
    )


def _fonts(fonts: Iterable[str]) -> str:
    """Format a font list as a Typst array.

    Args:
        fonts: Font family names in order of preference.

    Returns:
        The Typst array literal.
    """
    return "(" + ", ".join(_string(font) for font in fonts) + ")"


class _Converter:
    """Convert a markdown-it syntax tree to Typst markup."""

    def __init__(self, base_dir: Path | None, images: bool) -> None:
        """Initialise the converter.

        Args:
            base_dir: Directory relative image paths resolve against, or
                ``None`` when local images can't be resolved.
            images: Embed local images? Turned off to recover from images
                Typst can't decode.
        """
        self._base_dir = base_dir
        self._images = images

    def blocks(self, nodes: Iterable[SyntaxTreeNode]) -> str:
        """Convert a sequence of block nodes.

        Args:
            nodes: The block nodes.

        Returns:
            Typst markup with blocks separated by paragraph breaks.
        """
        return "\n\n".join(
            converted for node in nodes if (converted := self.block(node))
        )

    def block(self, node: SyntaxTreeNode) -> str:  # pylint: disable=too-many-return-statements
        """Convert a single block node.

        Args:
            node: The block node.

        Returns:
            The Typst markup for the block.
        """
        kind = node.type
        if kind == "paragraph":
            return self.inline(node.children)
        if kind == "heading":
            level = int(node.tag[1:])
            return f"#heading(level: {level})[{self.inline(node.children)}];"
        if kind == "bullet_list":
            return self._list("list", node)
        if kind == "ordered_list":
            return self._list("enum", node)
        if kind == "blockquote":
            return f"#quote(block: true)[{self.blocks(node.children)}];"
        if kind in ("fence", "code_block"):
            language = (node.info or "").strip().split(maxsplit=1)
            lang = f"lang: {_string(language[0])}, " if language else ""
            return f"#raw(block: true, {lang}{_string(node.content.rstrip(chr(10)))});"
        if kind == "hr":
            return "#line(length: 100%);"
        if kind == "table":
            return self._table(node)
        if kind == "html_block":
            if node.content.lstrip().startswith("<!--"):
                return ""
            return f'#raw(block: true, lang: "html", {_string(node.content.rstrip())});'
        # front_matter and anything unknown is left out.
        return ""

    def _list(self, function: str, node: SyntaxTreeNode) -> str:
        """Convert a bullet or ordered list.

        Args:
            function: ``list`` or ``enum``.
            node: The list node.

        Returns:
            The Typst list call.
        """
        tight = all(
            child.hidden
            for item in node.children
            for child in item.children
            if child.type == "paragraph"
        )
        arguments = [f"tight: {'true' if tight else 'false'}"]
        if function == "enum" and (start := node.attrs.get("start")) is not None:
            arguments.append(f"start: {int(start)}")
        items = ", ".join(f"[{self._list_item(item)}]" for item in node.children)
        return f"#{function}({', '.join(arguments)}, {items});"

    def _list_item(self, item: SyntaxTreeNode) -> str:
        """Convert a list item, rendering GFM task markers as checkboxes.

        Args:
            item: The list item node.

        Returns:
            The Typst markup for the item body.
        """
        if all(child.hidden for child in item.children if child.type == "paragraph"):
            # Tight item: keep any nested list snug against the text.
            body = "\n".join(
                converted for child in item.children if (converted := self.block(child))
            )
        else:
            body = self.blocks(item.children)
        for marker, box in (
            ("\\[ \\] ", "#md-task(false);#h(0.3em); "),
            ("\\[x\\] ", "#md-task(true);#h(0.3em); "),
            ("\\[X\\] ", "#md-task(true);#h(0.3em); "),
        ):
            if body.startswith(marker):
                return box + body[len(marker) :]
        return body

    def _table(self, node: SyntaxTreeNode) -> str:
        """Convert a GFM table.

        Args:
            node: The table node.

        Returns:
            The Typst table call.
        """
        rows: list[tuple[bool, list[SyntaxTreeNode]]] = [
            (section.type == "thead", row.children)
            for section in node.children
            for row in section.children
        ]
        if not rows:
            return ""
        columns = max(len(cells) for _, cells in rows)
        alignments = []
        for cell in rows[0][1]:
            style = str(cell.attrs.get("style", ""))
            alignments.append(
                "center" if "center" in style else "right" if "right" in style else "left"
            )
        alignments += ["left"] * (columns - len(alignments))

        def cells(row: list[SyntaxTreeNode]) -> str:
            converted = [f"[{self.inline(cell.children)}]" for cell in row]
            converted += ["[]"] * (columns - len(converted))
            return ", ".join(converted)

        header = [f"table.header({cells(row)})" for is_head, row in rows if is_head]
        body = [cells(row) for is_head, row in rows if not is_head]
        return (
            f"#table(columns: {columns}, align: ({', '.join(alignments)},), "
            f"{', '.join([*header, *body])});"
        )

    def inline(self, nodes: Iterable[SyntaxTreeNode]) -> str:
        """Convert inline nodes (flattening the ``inline`` wrapper).

        Args:
            nodes: The inline nodes.

        Returns:
            The Typst markup for the inline content.
        """
        return "".join(self._inline(node) for node in nodes)

    def _inline(self, node: SyntaxTreeNode) -> str:  # pylint: disable=too-many-return-statements
        """Convert a single inline node.

        Args:
            node: The inline node.

        Returns:
            The Typst markup for the node.
        """
        kind = node.type
        if kind == "inline":
            return self.inline(node.children)
        if kind == "text":
            return _escape(node.content)
        if kind == "softbreak":
            return " "
        if kind == "hardbreak":
            return "#linebreak();"
        if kind == "strong":
            return f"#strong[{self.inline(node.children)}];"
        if kind == "em":
            return f"#emph[{self.inline(node.children)}];"
        if kind == "s":
            return f"#strike[{self.inline(node.children)}];"
        if kind == "code_inline":
            return f"#raw({_string(node.content)});"
        if kind == "link":
            href = str(node.attrs.get("href", ""))
            return f"#link({_string(href)})[{self.inline(node.children)}];"
        if kind == "image":
            return self._image(node)
        if kind == "html_inline":
            return "#linebreak();" if node.content.lower().startswith("<br") else ""
        return _escape(node.content)

    def _image(self, node: SyntaxTreeNode) -> str:
        """Convert an image, embedding it when it's a readable local file.

        Typst can only read files under its root, so paths are given
        relative to the filesystem anchor that :func:`typst_root` returns.

        Args:
            node: The image node.

        Returns:
            Markup for the image, or its alt text when it can't be embedded.
        """
        alt = self.inline(node.children)
        source = str(node.attrs.get("src", ""))
        fallback = f"#emph[\\[{alt or 'image'}\\]];"
        if not self._images or self._base_dir is None or "://" in source:
            return fallback
        path = (self._base_dir / source).resolve()
        if path.suffix.lower() not in _IMAGE_SUFFIXES or not path.is_file():
            return fallback
        try:
            rooted = "/" + path.relative_to(path.anchor).as_posix()
        except ValueError:
            return fallback
        return f"#md-image({_string(rooted)});"


_PARSER = MarkdownIt("gfm-like").use(front_matter.front_matter_plugin)
"""Shared parser, configured like the app's Markdown widgets."""


def markdown_to_typst(markdown: str, base_dir: Path | None, images: bool = True) -> str:
    """Convert Markdown to Typst markup.

    Args:
        markdown: The Markdown source.
        base_dir: Directory relative image paths resolve against.
        images: Embed local images?

    Returns:
        Typst markup for the document body (no page setup).
    """
    tree = SyntaxTreeNode(_PARSER.parse(markdown))
    return _Converter(base_dir, images).blocks(tree.children)


def code_to_typst(text: str, language: str | None) -> str:
    """Wrap plain text or source code as a single highlighted block.

    Args:
        text: The file contents.
        language: Syntax highlighting language, if known.

    Returns:
        Typst markup for the document body.
    """
    lang = f"lang: {_string(language)}, " if language else ""
    return f"#raw(block: true, {lang}{_string(text)});"


def typst_root(base_dir: Path | None) -> str:
    """The Typst project root for a document.

    Rooting at the filesystem anchor lets Markdown reference images anywhere
    on the same drive, including ``../`` paths.

    Args:
        base_dir: The document's directory, if it has one.

    Returns:
        The root directory to compile with.
    """
    return (base_dir or Path.cwd()).resolve().anchor


def page_ppi(cell_width: int) -> float:
    """Pick the render resolution so body text matches the terminal font.

    A monospace glyph advances roughly 0.6em, so the cell width gives the
    terminal font size; the body is set a touch larger for comfort.

    Args:
        cell_width: Width of a terminal cell in pixels.

    Returns:
        Pixels per inch to render at.
    """
    terminal_font_px = cell_width / 0.6
    return terminal_font_px * 1.05 * 72 / BODY_SIZE_PT


def build_document(body: str, width_px: int, ppi: float, palette: TypesetPalette) -> str:
    """Wrap a converted body in page setup and styling.

    Args:
        body: Typst markup from :func:`markdown_to_typst` or
            :func:`code_to_typst`.
        width_px: Target image width in pixels.
        ppi: Resolution the document will be rendered at.
        palette: Colours to use.

    Returns:
        A complete Typst document.
    """
    width_pt = width_px * 72 / ppi
    margin_x = max(14.0, (width_pt - MAX_MEASURE_PT) / 2)
    code_theme = (
        f"#set raw(theme: bytes({_string(_dark_code_theme())}))\n" if palette.dark else ""
    )
    return f"""\
#set page(width: {width_pt:.3f}pt, height: auto, margin: (x: {margin_x:.3f}pt, top: 16pt, bottom: 28pt), fill: rgb("{palette.background}"))
#set text(font: {_fonts(_SANS_FONTS)}, size: {BODY_SIZE_PT}pt, fill: rgb("{palette.foreground}"))
#set par(leading: 0.75em, spacing: 1.3em)
{code_theme}#show raw: set text(font: {_fonts(_MONO_FONTS)}, size: {BODY_SIZE_PT * 0.9:.2f}pt)
#show raw.where(block: true): it => block(width: 100%, fill: rgb("{palette.code_background}"), stroke: 0.5pt + rgb("{palette.border}"), inset: (x: 11pt, y: 10pt), radius: 5pt, it)
#show raw.where(block: false): it => box(fill: rgb("{palette.code_background}"), inset: (x: 3pt), outset: (y: 3pt), radius: 3pt, it)
#show link: set text(fill: rgb("{palette.accent}"))
#show heading: set text(weight: 600)
#show heading: set block(above: 1.7em, below: 0.85em)
#show heading.where(level: 1): it => block(width: 100%, above: 1.4em, below: 1em, inset: (bottom: 0.7em), stroke: (bottom: 0.5pt + rgb("{palette.border}")), text(size: 1.9em, weight: 600, it.body))
#show heading.where(level: 2): set text(size: 1.45em)
#show heading.where(level: 3): set text(size: 1.2em)
#show heading.where(level: 5): set text(fill: rgb("{palette.muted}"))
#show heading.where(level: 6): set text(fill: rgb("{palette.muted}"))
#set list(marker: ([•], [◦], [▪]), indent: 0.3em, body-indent: 0.6em)
#set enum(indent: 0.3em, body-indent: 0.6em)
#show quote.where(block: true): it => block(stroke: (left: 2.5pt + rgb("{palette.border}")), inset: (left: 12pt, y: 3pt), text(fill: rgb("{palette.muted}"), it.body))
#set table(stroke: 0.5pt + rgb("{palette.border}"), inset: (x: 8pt, y: 6pt))
#show table.cell.where(y: 0): set text(weight: 600)
#set line(stroke: 0.5pt + rgb("{palette.border}"))
#let md-task(done) = box(width: 0.8em, height: 0.8em, baseline: 0.1em, radius: 2pt, stroke: 0.8pt + rgb(if done {{ "{palette.accent}" }} else {{ "{palette.muted}" }}), fill: if done {{ rgb("{palette.accent}") }} else {{ none }}, if done {{ align(center + horizon, text(size: 0.65em, fill: rgb("{palette.background}"), weight: 700, "✓")) }})
#let md-image(path) = layout(size => {{
  let natural = image(path)
  if measure(natural).width > size.width {{ image(path, width: 100%) }} else {{ natural }}
}})

{body}
"""


class TypesetError(Exception):
    """Raised when Typst can't compile a document."""


class TypesetRenderer:
    """Compiles Typst documents in a long-lived worker process.

    See :mod:`tui_md_editor.utility.typeset_worker` for the protocol.
    """

    def __init__(self) -> None:
        """Initialise the renderer; the worker starts on first use."""
        self._process: asyncio.subprocess.Process | None = None
        self._lock = asyncio.Lock()

    async def render(self, source: str, root: str, ppi: float) -> bytes:
        """Compile a document to PNG without blocking the event loop.

        Args:
            source: The Typst document.
            root: The project root.
            ppi: Pixels per inch.

        Returns:
            The PNG image data.

        Raises:
            TypesetError: If Typst reports an error or the worker dies.
        """
        request = json.dumps({"source": source, "root": root, "ppi": ppi}).encode("utf-8")
        # Shielded so a cancelled caller (a newer render superseding this
        # one) can't abandon a half-read reply and desync the pipe.
        status, payload = await asyncio.shield(self._exchange(request))
        if status != 0:
            raise TypesetError(payload.decode("utf-8", "replace"))
        return payload

    async def _exchange(self, request: bytes) -> tuple[int, bytes]:
        """Send one request to the worker and read its reply.

        Args:
            request: The encoded request.

        Returns:
            The status byte and payload.
        """
        async with self._lock:
            if self._process is None or self._process.returncode is not None:
                self._process = await asyncio.create_subprocess_exec(
                    sys.executable,
                    "-m",
                    "tui_md_editor.utility.typeset_worker",
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                )
            process = self._process
            assert process.stdin is not None and process.stdout is not None
            try:
                process.stdin.write(len(request).to_bytes(4, "big") + request)
                await process.stdin.drain()
                header = await process.stdout.readexactly(5)
                payload = await process.stdout.readexactly(int.from_bytes(header[1:], "big"))
            except (asyncio.IncompleteReadError, ConnectionError) as error:
                self._process = None
                return 1, f"The typesetting process stopped unexpectedly ({error}).".encode()
            return header[0], payload

    async def shutdown(self) -> None:
        """Stop the worker process and release its pipes."""
        process, self._process = self._process, None
        self._lock = asyncio.Lock()
        if process is None or process.returncode is not None:
            return
        try:
            process.kill()
        except ProcessLookupError:
            pass
        try:
            await asyncio.wait_for(process.wait(), timeout=2)
        except asyncio.TimeoutError:
            pass


renderer = TypesetRenderer()
"""The shared renderer used by every typeset preview."""
