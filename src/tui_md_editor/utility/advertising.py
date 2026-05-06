"""Provides the 'branding' for the application."""

from typing_extensions import Final

from .. import __version__

ORGANISATION_NAME: Final[str] = "tui-md-editor"
"""The organisation name to use when creating namespaced resources."""

ORGANISATION_TITLE: Final[str] = "TUI MD Editor"
"""The organisation title."""

ORGANISATION_URL: Final[str] = "https://github.com/"
"""The organisation URL."""

PACKAGE_NAME: Final[str] = "tui-md-editor"
"""The name of the package."""

APPLICATION_TITLE: Final[str] = "TUI MD Editor"
"""The title of the application."""

USER_AGENT: Final[str] = f"{PACKAGE_NAME} v{__version__}"
"""The user agent to use when making web requests."""

DISCORD: Final[str] = ""
"""The link to the Discord server."""

TEXTUAL_URL: Final[str] = "https://textual.textualize.io/"
"""The URL people should visit to find out more about Textual."""
