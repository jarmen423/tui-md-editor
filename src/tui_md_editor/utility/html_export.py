"""Render Markdown as a styled standalone HTML document.

Used by the ``:export html <path>`` omnibox command and the live browser
preview server (see :mod:`tui_md_editor.utility.preview_server`). The page
imitates the clean reading aesthetic of Vercel-style docs: Geist Sans for
prose, Geist Mono for code, a constrained measure, and a quiet dark/light
palette.

Key Technologies/APIs:
    - :class:`markdown_it.MarkdownIt` with the ``gfm-like`` preset
    - ``mdit_py_plugins.front_matter`` (strips YAML front matter)
"""

from __future__ import annotations

from html import escape

from markdown_it import MarkdownIt
from mdit_py_plugins import front_matter

GEIST_FONTS_URL = (
    "https://fonts.googleapis.com/css2"
    "?family=Geist:wght@400;500;600;700"
    "&family=Geist+Mono:wght@400;500"
    "&display=swap"
)
"""Google Fonts stylesheet serving Geist Sans and Geist Mono."""

_SANS_STACK = (
    '"Geist Sans", "Geist", -apple-system, BlinkMacSystemFont, '
    '"Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif'
)
_MONO_STACK = (
    '"Geist Mono", ui-monospace, SFMono-Regular, "SF Mono", Menlo, '
    'Consolas, "Liberation Mono", monospace'
)


_DARK_PALETTE = {
    "bg": "#0a0a0a",
    "fg": "#ededed",
    "muted": "#a1a1a1",
    "border": "#262626",
    "code_bg": "#111111",
    "accent": "#4493f8",
}

_LIGHT_PALETTE = {
    "bg": "#ffffff",
    "fg": "#171717",
    "muted": "#666666",
    "border": "#e5e5e5",
    "code_bg": "#f4f4f5",
    "accent": "#0070f3",
}

LIVE_RELOAD_SCRIPT = """<script>
(function () {
  var source = new EventSource("/events");
  source.onmessage = function () {
    fetch("/body", { cache: "no-store" })
      .then(function (response) { return response.text(); })
      .then(function (html) {
        var y = window.scrollY;
        var main = document.querySelector("main");
        if (main) { main.innerHTML = html; }
        window.scrollTo(0, y);
      })
      .catch(function () {});
  };
})();
</script>"""
"""Live-reload snippet for the browser preview server.

Listens for server-sent events and swaps the ``<main>`` content in place,
preserving the reader's scroll position so the page never snaps to top.
The browser tab scrolls independently of the terminal preview.
"""


def render_markdown_body(markdown_text: str) -> str:
    """Render Markdown source as an HTML fragment (no page chrome).

    Args:
        markdown_text: Raw Markdown source to render.

    Returns:
        The rendered HTML fragment, suitable for the ``<main>`` body.
    """
    md = MarkdownIt("gfm-like").use(front_matter.front_matter_plugin)
    return md.render(markdown_text)


def render_html_document(
    title: str, markdown_text: str, *, dark: bool = True, live_reload: bool = False
) -> str:
    """Render Markdown source as a complete styled HTML page.

    Args:
        title: Page ``<title>`` and fallback heading context. HTML-escaped.
        markdown_text: Raw Markdown source to render into the page body.
        dark: Use the dark palette (default) or the light palette.
        live_reload: Inject the live-reload snippet so the page refreshes
            from the preview server without a manual reload.

    Returns:
        A complete UTF-8 HTML document as a string.
    """
    body = render_markdown_body(markdown_text)
    palette = _DARK_PALETTE if dark else _LIGHT_PALETTE
    scheme = "dark" if dark else "light"
    live_script = LIVE_RELOAD_SCRIPT if live_reload else ""
    return f"""<!DOCTYPE html>
<html lang="en" data-theme="{scheme}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="{scheme}">
<title>{escape(title)}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="{GEIST_FONTS_URL}" rel="stylesheet">
<style>
:root {{
  color-scheme: {scheme};
  --bg: {palette["bg"]};
  --fg: {palette["fg"]};
  --muted: {palette["muted"]};
  --border: {palette["border"]};
  --code-bg: {palette["code_bg"]};
  --accent: {palette["accent"]};
}}
* {{ box-sizing: border-box; }}
body {{
  margin: 0;
  background: var(--bg);
  color: var(--fg);
  font-family: {_SANS_STACK};
  font-size: 16px;
  line-height: 1.75;
  -webkit-font-smoothing: antialiased;
}}
main {{
  max-width: 720px;
  margin: 0 auto;
  padding: 3rem 1.5rem 4rem;
}}
h1, h2, h3, h4, h5, h6 {{
  line-height: 1.25;
  letter-spacing: -0.02em;
  margin: 2em 0 0.6em;
  font-weight: 600;
}}
h1 {{ font-size: 2rem; }}
h2 {{ font-size: 1.5rem; padding-bottom: 0.3em; border-bottom: 1px solid var(--border); }}
h3 {{ font-size: 1.25rem; }}
h1:first-child, h2:first-child {{ margin-top: 0; }}
p {{ margin: 0 0 1.1em; }}
a {{ color: var(--accent); text-decoration: none; }}
a:hover {{ text-decoration: underline; }}
code {{
  font-family: {_MONO_STACK};
  font-size: 0.875em;
}}
p code, li code, td code, th code {{
  background: var(--code-bg);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 0.15em 0.4em;
  white-space: nowrap;
}}
pre {{
  background: var(--code-bg);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 1rem 1.25rem;
  overflow-x: auto;
  line-height: 1.6;
}}
pre code {{
  background: none;
  border: none;
  padding: 0;
  white-space: pre;
}}
blockquote {{
  margin: 1.5em 0;
  padding: 0.1em 1em;
  border-left: 3px solid var(--border);
  color: var(--muted);
}}
ul, ol {{ padding-left: 1.5em; margin: 0 0 1.1em; }}
li {{ margin: 0.3em 0; }}
li > ul, li > ol {{ margin-bottom: 0; }}
hr {{
  border: none;
  border-top: 1px solid var(--border);
  margin: 2.5em 0;
}}
table {{
  border-collapse: collapse;
  width: 100%;
  margin: 1.5em 0;
  font-size: 0.95em;
}}
th, td {{
  border: 1px solid var(--border);
  padding: 0.6em 0.9em;
  text-align: left;
}}
th {{ font-weight: 600; }}
img {{ max-width: 100%; height: auto; border-radius: 8px; }}
</style>
</head>
<body>
<main>
{body}</main>
{live_script}
</body>
</html>
"""
