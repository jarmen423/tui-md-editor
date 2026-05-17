"""Support code for testing files for their potential type."""

from functools import singledispatch
from pathlib import Path
from typing import Any

from httpx import URL

from ..data.config import load_config

# Extensions we treat as editable text files.
_TEXT_EXTENSIONS: set[str] = {
    ".txt",
    ".py",
    ".js",
    ".ts",
    ".jsx",
    ".tsx",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".cfg",
    ".sh",
    ".bash",
    ".zsh",
    ".ps1",
    ".css",
    ".html",
    ".htm",
    ".xml",
    ".rs",
    ".go",
    ".java",
    ".c",
    ".cpp",
    ".h",
    ".hpp",
    ".swift",
    ".kt",
    ".scala",
    ".rb",
    ".php",
    ".pl",
    ".lua",
    ".r",
    ".sql",
    ".md",
    ".markdown",
    ".dockerfile",
    ".makefile",
    ".cmake",
    ".gradle",
    ".vim",
    ".el",
    ".clj",
    ".erl",
    ".ex",
    ".exs",
    ".fs",
    ".fsx",
    ".hs",
    ".lhs",
    ".jl",
    ".ml",
    ".mli",
    ".nim",
    ".pas",
    ".pp",
    ".proto",
    ".scm",
    ".ss",
    ".tcl",
    ".tf",
    ".v",
    ".vhdl",
    ".verilog",
    ".zig",
}


def _looks_binary(path: Path) -> bool:
    """Heuristic: read first 8KB and look for null bytes."""
    try:
        with path.open("rb") as fh:
            chunk = fh.read(8192)
    except OSError:
        return True
    return b"\x00" in chunk


@singledispatch
def maybe_markdown(resource: Any) -> bool:
    """Does the given resource look like it's a Markdown file?

    Args:
        resource: The resource to test.

    Returns:
        `True` if the resources looks like a Markdown file, `False` if not.
    """
    del resource
    return False


@maybe_markdown.register
def _(resource: Path) -> bool:
    return resource.suffix.lower() in load_config().markdown_extensions


@maybe_markdown.register
def _(resource: str) -> bool:
    return maybe_markdown(Path(resource))


@maybe_markdown.register
def _(resource: URL) -> bool:
    return maybe_markdown(resource.path)


def is_text_file(path: Path) -> bool:
    """Does the path look like an editable text file?

    Checks extension against a known list, and for files without a
    recognised extension falls back to a binary-content heuristic.

    Args:
        path: The path to test.

    Returns:
        `True` if the file appears to be a text file.
    """
    suffix = path.suffix.lower()
    if suffix in _TEXT_EXTENSIONS:
        return True
    if suffix == "":
        # No extension — could be a script or plain text.
        if path.exists():
            return not _looks_binary(path)
        return True
    if path.exists():
        return not _looks_binary(path)
    return False


def language_for_path(path: Path) -> str | None:
    """Return the TextArea language name for a given file path.

    Textual 0.53.1 only ships a handful of builtin highlighters.
    For everything else we return ``None`` (plain text).

    Args:
        path: The path to map.

    Returns:
        A language string recognised by Textual's TextArea, or `None`.
    """
    suffix = path.suffix.lower()
    mapping: dict[str, str] = {
        ".py": "python",
        ".sh": "bash",
        ".bash": "bash",
        ".zsh": "bash",
        ".css": "css",
        ".html": "html",
        ".htm": "html",
        ".json": "json",
        ".md": "markdown",
        ".markdown": "markdown",
        ".sql": "sql",
        ".toml": "toml",
        ".yaml": "yaml",
        ".yml": "yaml",
    }
    return mapping.get(suffix)


def is_likely_url(candidate: str) -> bool:
    """Does the given value look something like a URL?

    Args:
        candidate: The candidate to check.

    Returns:
        `True` if the string is likely a URL, `False` if not.
    """
    # Quick and dirty for now.
    url = URL(candidate)
    return url.is_absolute_url and url.scheme in ("http", "https")
