"""Serve a live-reloading browser preview of the current document.

Runs a small localhost-only HTTP server (standard library only) in a
background thread. The served page re-renders from the editor on every
:meth:`PreviewServer.update` and pushes a notification to connected
browsers over Server-Sent Events, so edits appear without a manual
reload. The browser tab keeps its own scroll position.

Key Technologies/APIs:
    - :class:`http.server.ThreadingHTTPServer` (stdlib)
    - Server-Sent Events (``text/event-stream``)
    - :func:`tui_md_editor.utility.html_export.render_html_document`
"""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from queue import Empty, Queue
from threading import Lock, Thread

from .html_export import render_html_document, render_markdown_body


class _PreviewHTTPServer(ThreadingHTTPServer):
    """HTTP server holding the live preview state."""

    daemon_threads = True
    """Client handler threads must not keep the process alive."""

    allow_reuse_address = True
    """Allow quick restarts of the preview on the same port."""

    def __init__(
        self,
        title: str,
        markdown_text: str,
        *,
        dark: bool = True,
    ) -> None:
        """Bind a localhost-only server for the given document.

        Args:
            title: Page ``<title>`` for the preview.
            markdown_text: Initial Markdown source to render.
            dark: Use the dark palette (default) or the light palette.
        """
        super().__init__(("127.0.0.1", 0), _PreviewRequestHandler)
        self._state_lock = Lock()
        self._title = title
        self._markdown_text = markdown_text
        self._dark = dark
        self._version = 0
        self._clients: list[Queue[int | None]] = []
        self._closed = False


class _PreviewRequestHandler(BaseHTTPRequestHandler):
    """Serve the preview page, body fragment, and event stream."""

    server: _PreviewHTTPServer

    def log_message(self, *args: object) -> None:
        """Silence per-request stderr logging."""
        del args

    def _send_html(self, payload: str) -> None:
        """Send a UTF-8 HTML response with no caching.

        Args:
            payload: The HTML body to send.
        """
        data = payload.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _render_page(self) -> str:
        """Render the full live-reload page from current state."""
        with self.server._state_lock:
            return render_html_document(
                self.server._title,
                self.server._markdown_text,
                dark=self.server._dark,
                live_reload=True,
            )

    def _render_body(self) -> str:
        """Render just the ``<main>`` fragment from current state."""
        with self.server._state_lock:
            return render_markdown_body(self.server._markdown_text)

    def do_GET(self) -> None:  # noqa: N802 (stdlib handler naming)
        """Route ``GET`` requests to the page, fragment, or event stream."""
        if self.path in ("/", "/index.html"):
            self._send_html(self._render_page())
        elif self.path == "/body":
            self._send_html(self._render_body())
        elif self.path == "/events":
            self._serve_events()
        else:
            self.send_error(404, "Not found")

    def _serve_events(self) -> None:
        """Hold open an SSE stream, pushing a version on every update."""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        client: Queue[int | None] = Queue()
        with self.server._state_lock:
            if self.server._closed:
                return
            self.server._clients.append(client)
            version = self.server._version
        try:
            self.wfile.write(f"data: {version}\n\n".encode("utf-8"))
            self.wfile.flush()
            while True:
                try:
                    version = client.get(timeout=15)
                except Empty:
                    # Keep-alive comment; also surfaces dead clients.
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
                    continue
                if version is None or self.server._closed:
                    return
                self.wfile.write(f"data: {version}\n\n".encode("utf-8"))
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, ValueError):
            # Browser went away; just drop the subscription.
            pass
        finally:
            with self.server._state_lock:
                if client in self.server._clients:
                    self.server._clients.remove(client)


class PreviewServer:
    """A localhost-only live preview server for one Markdown document."""

    def __init__(self, title: str, markdown_text: str, *, dark: bool = True) -> None:
        """Create (but do not start) a preview server.

        Args:
            title: Page ``<title>`` for the preview.
            markdown_text: Initial Markdown source to render.
            dark: Use the dark palette (default) or the light palette.
        """
        self._server = _PreviewHTTPServer(title, markdown_text, dark=dark)
        self._thread = Thread(
            target=self._server.serve_forever,
            name="browser-preview",
            daemon=True,
        )
        self._running = False

    @property
    def url(self) -> str:
        """The base URL of the preview (e.g. ``http://127.0.0.1:PORT/``)."""
        host, port = self._server.server_address
        return f"http://{host}:{port}/"

    @property
    def running(self) -> bool:
        """Whether the server thread is currently serving."""
        return self._running

    def start(self) -> PreviewServer:
        """Start serving in a background daemon thread.

        Returns:
            The server itself, for chaining.
        """
        if not self._running:
            self._running = True
            self._thread.start()
        return self

    def update(self, markdown_text: str, *, title: str, dark: bool) -> bool:
        """Push new content to connected browsers.

        Args:
            markdown_text: Current Markdown source to render.
            title: Page ``<title>`` for the preview.
            dark: Use the dark palette or the light palette.

        Returns:
            ``True`` if anything changed (and clients were notified),
            ``False`` if the state was identical.
        """
        server = self._server
        with server._state_lock:
            if (
                markdown_text == server._markdown_text
                and title == server._title
                and dark == server._dark
            ):
                return False
            server._markdown_text = markdown_text
            server._title = title
            server._dark = dark
            server._version += 1
            version = server._version
            clients = list(server._clients)
        for client in clients:
            client.put(version)
        return True

    def stop(self) -> None:
        """Shut the server down and release the port."""
        server = self._server
        with server._state_lock:
            if server._closed:
                return
            server._closed = True
            clients = list(server._clients)
        for client in clients:
            client.put(None)
        self._running = False
        server.shutdown()
        server.server_close()
        self._thread.join(timeout=5)
