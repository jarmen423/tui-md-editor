"""A draggable resize handle for the navigation sidebar."""

from __future__ import annotations

from textual import events
from textual.reactive import reactive
from textual.widget import Widget


class ResizeHandle(Widget):
    """A thin vertical bar that can be dragged to resize its parent."""

    DEFAULT_CSS = """
    ResizeHandle {
        width: 1;
        height: 100%;
        background: $primary-darken-2;
    }
    ResizeHandle:hover {
        background: $accent;
    }
    ResizeHandle.active {
        background: $accent;
    }
    """

    grabbed: reactive[bool] = reactive(False)
    """Is the handle currently being dragged?"""

    def __init__(self) -> None:
        """Initialise the resize handle."""
        super().__init__()
        self._start_position: int = 0
        self._start_width: int = 0

    async def _on_mouse_down(self, event: events.MouseDown) -> None:
        """Capture the mouse when the user clicks the handle."""
        event.stop()
        self.capture_mouse()

    def _on_mouse_capture(self, event: events.MouseCapture) -> None:
        """Record the starting position and parent width."""
        self.grabbed = True
        self._start_position = event.mouse_position.x
        if self.parent is not None:
            self._start_width = self.parent.size.width
        self.add_class("active")

    async def _on_mouse_move(self, event: events.MouseMove) -> None:
        """Update the parent width based on mouse movement."""
        if not self.grabbed or self.parent is None:
            return
        delta = event.screen_x - self._start_position
        # When docked right, dragging left increases width.
        if getattr(self.parent, "docked_left", True):
            new_width = self._start_width + delta
        else:
            new_width = self._start_width - delta
        # Clamp to reasonable bounds.
        new_width = max(20, min(80, new_width))
        self.parent.styles.width = new_width
        event.stop()

    def _on_mouse_release(self, event: events.MouseRelease) -> None:
        """Release the mouse and clear the grabbed state."""
        self.grabbed = False
        self.remove_class("active")
        event.stop()

    async def _on_mouse_up(self, event: events.MouseUp) -> None:
        """Release the mouse on mouse up."""
        if self.grabbed:
            self.release_mouse()
            self.grabbed = False
            self.remove_class("active")
        event.stop()
