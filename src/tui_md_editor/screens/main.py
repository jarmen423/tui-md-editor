"""The main screen for the application."""

from __future__ import annotations

from functools import partial
from pathlib import Path
from typing import Awaitable, Callable
from webbrowser import open as open_url

from httpx import URL
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.events import Key, Paste
from textual.screen import Screen
from textual.widgets import Footer, Markdown, OptionList

from .. import __version__
from ..data import load_config, load_history, save_config, save_history
from ..dialogs import ErrorDialog, HelpDialog, InformationDialog, InputDialog, YesNoDialog
from ..utility import (
    build_raw_bitbucket_url,
    build_raw_codeberg_url,
    build_raw_github_url,
    build_raw_gitlab_url,
    is_likely_url,
    is_text_file,
    maybe_markdown,
)
from ..utility.advertising import (
    APPLICATION_TITLE,
    ORGANISATION_NAME,
    ORGANISATION_TITLE,
    ORGANISATION_URL,
    PACKAGE_NAME,
    TEXTUAL_URL,
)
from ..widgets import Navigation, Omnibox, StatusBar, Viewer
from ..widgets.navigation_panes import Bookmarks, History, LocalFiles


class Main(Screen[None]):  # pylint:disable=too-many-public-methods
    """The main screen for the application."""

    DEFAULT_CSS = """
    .focusable {
        border: blank;
    }

    .focusable:focus {
        border: heavy $accent !important;
    }

    #omnibox_container {
        dock: top;
        height: auto;
    }

    Omnibox {
        height: 3;
        padding: 0;
    }

    #omnibox_dropdown {
        height: auto;
        max-height: 12;
        display: none;
        background: $surface;
        border: solid $primary;
    }

    #omnibox_dropdown:focus {
        border: solid $accent;
    }

    #omnibox_dropdown > .option-list--option-highlighted {
        background: $accent 50%;
        color: $text;
    }

    Screen Tabs {
        border: blank;
        height: 5;
    }

    Screen Tabs:focus {
        border: heavy $accent !important;
        height: 5;
    }

    Screen TabbedContent TabPane {
        padding: 0 1;
        border: blank;
    }

    Screen TabbedContent TabPane:focus-within {
        border: heavy $accent !important;
    }

    """

    BINDINGS = [
        Binding("/,:", "omnibox", "Omnibox", show=False),
        Binding("ctrl+b", "bookmarks", "", show=False),
        Binding("ctrl+d", "bookmark_this", "", show=False),
        Binding("ctrl+l", "local_files", "", show=False),
        Binding("ctrl+shift+e", "local_files", "Explorer"),
        Binding("ctrl+left", "backward", "", show=False),
        Binding("ctrl+right", "forward", "", show=False),
        Binding("ctrl+r", "reload", "", show=False),
        Binding("ctrl+t", "table_of_contents", "", show=False),
        Binding("ctrl+y", "history", "", show=False),
        Binding("escape", "escape", "", show=False),
        Binding("f1", "help", "Help"),
        Binding("f2", "about", "About"),
        Binding("ctrl+n", "navigation", "Navigation"),
        Binding("ctrl+e", "toggle_edit", "Edit", priority=True),
        Binding("ctrl+s", "save_file", "Save", priority=True),
        Binding("ctrl+f", "find", "Find", priority=True),
        Binding("ctrl+g", "goto_line", "Go To", priority=True),
        Binding("ctrl+n", "navigation", "Navigation"),
        Binding("alt+z", "toggle_wrap", "Wrap", priority=True),
        Binding("ctrl+backslash", "toggle_split", "Split", priority=True),
        Binding("ctrl+q", "app.quit", "Quit"),
        Binding("f10", "toggle_theme", "", show=False),
    ]
    """The keyboard bindings for the main screen."""

    def __init__(self, initial_location: str | None = None) -> None:
        """Initialise the main screen.

        Args:
            initial_location: The initial location to view.
        """
        super().__init__()
        self._initial_location = initial_location

    def compose(self) -> ComposeResult:
        """Compose the main screen.

        Returns:
            The result of composing the screen.
        """
        with Vertical(id="omnibox_container"):
            yield Omnibox(classes="focusable")
            yield OptionList(id="omnibox_dropdown")
        with Horizontal():
            yield Navigation()
            yield Viewer(classes="focusable", id="viewer")
        yield StatusBar()
        yield Footer()

    def visit(self, location: Path | URL, remember: bool = True) -> None:
        """Visit the given location.

        Args:
            location: The location to visit.
            remember: Should the visit be added to the history?
        """
        # If the location we've been given looks like it is markdown, be it
        # locally in the filesystem or out on the web...
        if maybe_markdown(location):
            # ...attempt to visit it in the viewer.
            self.query_one(Viewer).visit(location, remember)
        elif isinstance(location, Path):
            # So, it's not Markdown, but it *is* a Path of some sort.
            if is_text_file(location):
                # It's a text file we can edit — open in the viewer.
                self.query_one(Viewer).visit(location, remember)
            elif location.exists():
                # ...ask the OS to open it.
                open_url(f"file:///{location.absolute()}")
            else:
                # It's a Path but it doesn't exist, there's not much else we
                # can do with it.
                self.app.push_screen(
                    ErrorDialog(
                        "Does not exist",
                        f"Unable to open {location} because it does not exist.",
                    )
                )
        else:
            # By this point all that's left is it's a URL that, on the
            # surface, doesn't look like a Markdown file. Let's hand off to
            # the operating system anyway.
            open_url(str(location), new=2, autoraise=True)

    async def on_mount(self) -> None:
        """Set up the main screen once the DOM is ready."""

        # Currently Textual's Markdown can steal focus, which gets confusing
        # as it's not obvious *what* is focused. So let's stop it from
        # allowing the content to get focus.
        #
        # https://github.com/Textualize/textual/issues/2380
        for markdown in self.query(Markdown):
            markdown.can_focus_children = False

        # Load up any history that might be saved.
        if history := load_history():
            self.query_one(Viewer).load_history(history)

        # If we've not been tasked to start up looking at a very specific
        # location (in other words if no location was passed on the command
        # line), and if there is some history...
        if self._initial_location is None and history:
            # ...start up revisiting the last location the user was looking
            # at.
            self.query_one(Viewer).visit(history[-1], remember=False)
            self.query_one(Omnibox).value = str(history[-1])
        elif self._initial_location is not None:
            # Seems there is an initial location; so let's start up looking
            # at that.
            (omnibox := self.query_one(Omnibox)).value = self._initial_location
            await omnibox.action_submit()
        else:
            # No initial location and no history: open the local files
            # sidebar focused on the current working directory.
            self.query_one(Navigation).jump_to_local_files(Path.cwd())

    def on_navigation_hidden(self) -> None:
        """React to the navigation sidebar being hidden."""
        self.query_one(Viewer).focus()

    def on_omnibox_local_view_command(self, event: Omnibox.LocalViewCommand) -> None:
        """Handle the omnibox asking us to view a particular file.

        Args:
            event: The local view command event.
        """
        self.visit(event.path)

    def on_omnibox_remote_view_command(self, event: Omnibox.RemoteViewCommand) -> None:
        """Handle the omnibox asking us to view a particular URL.

        Args:
            event: The remote view command event.
        """
        self.visit(event.url)

    def on_omnibox_contents_command(self) -> None:
        """Handle being asked to show the table of contents."""
        self.action_table_of_contents()

    def on_omnibox_local_files_command(self) -> None:
        """Handle being asked to view the local files picker."""
        self.action_local_files()

    def on_omnibox_bookmarks_command(self) -> None:
        """Handle being asked to view the bookmarks."""
        self.action_bookmarks()

    def on_omnibox_create_path_command(
        self, event: Omnibox.CreatePathCommand
    ) -> None:
        """Handle a request to create a new file or directory.

        Args:
            event: The create path command event.
        """
        target = event.target
        kind = "directory" if event.is_directory else "file"

        def do_create(confirmed: bool) -> None:
            if not confirmed:
                return
            try:
                if event.is_directory:
                    target.mkdir(parents=True, exist_ok=True)
                    self.query_one(Navigation).jump_to_local_files(target)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.touch()
                    self.visit(target)
            except OSError as error:
                self.app.push_screen(
                    ErrorDialog(
                        f"Error creating {kind}",
                        f"{target}\n\n{error}.",
                    )
                )

        self.app.push_screen(
            YesNoDialog(
                f"Create {kind}?",
                f"{target} does not exist. Create it?",
            ),
            do_create,
        )

    def on_omnibox_new_file_command(self, event: Omnibox.NewFileCommand) -> None:
        """Handle a request to open a new untitled file.

        Args:
            event: The new file command event.
        """
        self.query_one(Viewer).new_file()

    def on_omnibox_export_html_command(
        self, event: Omnibox.ExportHtmlCommand
    ) -> None:
        """Handle a request to export the current document to HTML.

        Args:
            event: The export HTML command event.
        """
        viewer = self.query_one(Viewer)
        raw = viewer.editor.text
        if not raw:
            self.app.notify("Nothing to export.", severity="warning")
            return
        try:
            from markdown_it import MarkdownIt
            from mdit_py_plugins import front_matter

            md = MarkdownIt("gfm-like").use(front_matter.front_matter_plugin)
            html = md.render(raw)
            event.target.write_text(html, encoding="utf-8")
            self.app.notify(
                f"Exported to {event.target}", severity="information", timeout=2
            )
        except OSError as error:
            self.app.push_screen(
                ErrorDialog("Export failed", f"{event.target}\n\n{error}.")
            )

    def on_omnibox_show_file_suggestions(
        self, event: Omnibox.ShowFileSuggestions
    ) -> None:
        """Handle a request to show file suggestions in the dropdown.

        Args:
            event: The show file suggestions event.
        """
        dropdown = self.query_one("#omnibox_dropdown", OptionList)
        dropdown.clear_options()
        for path in event.paths:
            dropdown.add_option(str(path))
        dropdown.display = True

    def on_omnibox_hide_file_suggestions(self) -> None:
        """Handle a request to hide the file suggestions dropdown."""
        dropdown = self.query_one("#omnibox_dropdown", OptionList)
        dropdown.display = False

    def on_option_list_option_selected(
        self, event: OptionList.OptionSelected
    ) -> None:
        """Handle a file being selected from the omnibox dropdown.

        Args:
            event: The option selected event.
        """
        if event.option_list.id == "omnibox_dropdown":
            path_str = event.option_list.get_option_at_index(event.index).prompt
            self.visit(Path(path_str))
            event.option_list.display = False

    def on_key(self, event: Key) -> None:
        """Handle key events, including Escape in the dropdown.

        Args:
            event: The key event to handle.
        """
        if event.key == "escape":
            dropdown = self.query_one("#omnibox_dropdown", OptionList)
            if dropdown.display:
                dropdown.display = False
                self.query_one(Omnibox).focus()
                event.stop()

    def on_omnibox_local_chdir_command(self, event: Omnibox.LocalChdirCommand) -> None:
        """Handle being asked to view a new directory in the local files picker.

        Args:
            event: The chdir command event to handle.
        """
        if not event.target.exists():
            self.app.push_screen(
                ErrorDialog("No such directory", f"{event.target} does not exist.")
            )
        elif not event.target.is_dir():
            self.app.push_screen(
                ErrorDialog("Not a directory", f"{event.target} is not a directory.")
            )
        else:
            self.query_one(Navigation).jump_to_local_files(event.target)

    def on_omnibox_history_command(self) -> None:
        """Handle being asked to view the history."""
        self.action_history()

    async def _from_forge(
        self,
        forge: str,
        event: Omnibox.ForgeCommand,
        builder: Callable[[str, str, str | None, str | None], Awaitable[URL | None]],
    ) -> None:
        """Build a URL for getting a file from a given forge.

        Args:
            forge: The display name of the forge.
            event: The event that contains the request information for the file.
            builder: The function that builds the URL.
        """
        if url := await builder(
            event.owner, event.repository, event.branch, event.desired_file
        ):
            self.visit(url)
        else:
            self.app.push_screen(
                ErrorDialog(
                    f"Unable to work out a {forge} URL",
                    f"After trying a few options it hasn't been possible to work out the {forge} URL.\n\n"
                    "Perhaps the file you're after is on an unusual branch, or the spelling is wrong?",
                )
            )

    async def on_omnibox_git_hub_command(self, event: Omnibox.GitHubCommand) -> None:
        """Handle a GitHub file shortcut command.

        Args:
            event: The GitHub shortcut command event to handle.
        """
        await self._from_forge("GitHub", event, build_raw_github_url)

    async def on_omnibox_git_lab_command(self, event: Omnibox.GitLabCommand) -> None:
        """Handle a GitLab file shortcut command.

        Args:
            event: The GitLab shortcut command event to handle.
        """
        await self._from_forge("GitLab", event, build_raw_gitlab_url)

    async def on_omnibox_bit_bucket_command(
        self, event: Omnibox.BitBucketCommand
    ) -> None:
        """Handle a BitBucket shortcut command.

        Args:
            event: The BitBucket shortcut command event to handle.
        """
        await self._from_forge("BitBucket", event, build_raw_bitbucket_url)

    async def on_omnibox_codeberg_command(self, event: Omnibox.CodebergCommand) -> None:
        """Handle a Codeberg shortcut command.

        Args:
            event: The Codeberg shortcut command event to handle.
        """
        await self._from_forge("Codeberg", event, build_raw_codeberg_url)

    def on_omnibox_about_command(self) -> None:
        """Handle being asked to show the about dialog."""
        self.action_about()

    def on_omnibox_help_command(self) -> None:
        """Handle being asked to show the help document."""
        self.action_help()

    def on_omnibox_quit_command(self) -> None:
        """Handle being asked to quit."""
        self.app.exit()

    def on_local_files_goto(self, event: LocalFiles.Goto) -> None:
        """Visit a local file in the viewer.

        Args:
            event: The local file visit request event.
        """
        self.visit(event.location)

    def on_history_goto(self, event: History.Goto) -> None:
        """Handle a request to go to a location from history.

        Args:
            event: The event to handle.
        """
        self.visit(
            event.location, remember=event.location != self.query_one(Viewer).location
        )

    def on_history_delete(self, event: History.Delete) -> None:
        """Handle a request to delete an item from history.

        Args:
            event: The event to handle.
        """
        self.query_one(Viewer).delete_history(event.history_id)

    def on_history_clear(self) -> None:
        """handle a request to clear down all of history."""
        self.query_one(Viewer).clear_history()

    def on_bookmarks_goto(self, event: Bookmarks.Goto) -> None:
        """Handle a request to go to a bookmark.

        Args:
            event: The event to handle.
        """
        self.visit(event.bookmark.location)

    def on_viewer_location_changed(self, event: Viewer.LocationChanged) -> None:
        """Update for the location being changed.

        Args:
            event: The location change event.
        """
        # Update the omnibox with whatever is appropriate for the new location.
        viewer = event.viewer
        self.query_one(Omnibox).visiting = (
            str(viewer.location) if viewer.location is not None else ""
        )
        # Update the status bar.
        status = self.query_one(StatusBar)
        if viewer.location is None:
            status.file_name = "Untitled"
            status.file_type = ""
        elif isinstance(viewer.location, Path):
            status.file_name = viewer.location.name
            if viewer.is_plain_text:
                status.file_type = "Plain Text"
            else:
                status.file_type = "Markdown"
        else:
            status.file_name = str(viewer.location)
            status.file_type = "Remote"
        status.dirty = viewer.is_dirty
        status.words = viewer.word_count
        # Having safely arrived at a new location, that implies that we want
        # to focus on the viewer.
        viewer.focus()

    def on_viewer_edit_mode_changed(self, event: Viewer.EditModeChanged) -> None:
        """Update status bar when edit mode changes.

        Args:
            event: The edit mode change event.
        """
        status = self.query_one(StatusBar)
        status.line = event.viewer.cursor_location[0]
        status.column = event.viewer.cursor_location[1]

    def on_viewer_cursor_moved(self, event: Viewer.CursorMoved) -> None:
        """Update status bar when cursor moves.

        Args:
            event: The cursor moved event.
        """
        status = self.query_one(StatusBar)
        status.line = event.viewer.cursor_location[0]
        status.column = event.viewer.cursor_location[1]
        status.words = event.viewer.word_count
        status.dirty = event.viewer.is_dirty

    def on_viewer_document_saved(self, event: Viewer.DocumentSaved) -> None:
        """Update status bar when document is saved.

        Args:
            event: The document saved event.
        """
        status = self.query_one(StatusBar)
        status.dirty = False

    def on_viewer_history_updated(self, event: Viewer.HistoryUpdated) -> None:
        """Handle the viewer updating the history.

        Args:
            event: The history update event.
        """
        self.query_one(Navigation).history.update_from(event.viewer.history.locations)
        save_history(event.viewer.history.locations)

    def on_markdown_table_of_contents_updated(
        self, event: Markdown.TableOfContentsUpdated
    ) -> None:
        """Handle the table of contents of the document being updated.

        Args:
            event: The table of contents update event to handle.
        """
        # We don't handle this, the navigation pane does. Bounce the event
        # over there.
        self.query_one(Navigation).table_of_contents.on_table_of_contents_updated(event)

    def on_markdown_table_of_contents_selected(
        self, event: Markdown.TableOfContentsSelected
    ) -> None:
        """Handle the user selecting something from the table of contents.

        Args:
            event: The table of contents selection event to handle.
        """
        self.query_one(Viewer).scroll_to_block(event.block_id)

    def on_markdown_link_clicked(self, event: Markdown.LinkClicked) -> None:
        """Handle a link being clicked in the Markdown document.

        Args:
            event: The Markdown link click event to handle.
        """
        # We'll be using the current location to help work out some relative
        # things.
        current_location = self.query_one(Viewer).location
        # If the link we're to handle obviously looks like URL...
        if is_likely_url(event.href):
            # ...handle it as such. No point in trying to do anything else.
            self.visit(URL(event.href))
        elif isinstance(current_location, URL):
            # Seems we're currently visiting a remote location, and the href
            # looks like a simple file path, so let's make a best effort to
            # visit the file at the remote location.
            self.visit(current_location.copy_with().join(event.href))
        elif (local_file := Path(event.href)).exists():
            # It looks like a local file and it exists...
            self.visit(local_file)
        elif (
            isinstance(current_location, Path)
            and (local_file := (current_location.parent / Path(event.href)))
            .absolute()
            .exists()
        ):
            # It looks like a local file, and tested relative to the
            # document we found it exists in the local filesystem, so let's
            # assume that's what we're supposed to handle.
            self.visit(local_file)
        elif event.href.startswith("#") and event.markdown.goto_anchor(event.href[1:]):
            # The href started with a # and the remains of it were satisfied
            # as an anchor within the document of the Markdown. We should
            # have scrolled to about the right spot in the document so we
            # don't need to do anything else.
            pass
        else:
            # Yeah, not sure *what* this link is. Rather than silently fail,
            # let's let the user know we don't know how to process this.
            self.app.push_screen(
                ErrorDialog(
                    "Unable to handle link",
                    f"Unable to work out how to handle this link:\n\n{event.href}",
                )
            )

    def on_paste(self, event: Paste) -> None:
        """Handle a paste event.

        Args:
            event: The paste event.

        This method is here to capture paste events that look like the name
        of a local file (later I may add URL support too). The main purpose
        of this is to handle drag/drop into the terminal.
        """
        if (candidate_file := Path(event.text)).exists():
            self.visit(candidate_file)

    def action_navigation(self) -> None:
        """Toggle the availability of the navigation sidebar."""
        self.query_one(Navigation).toggle()

    def action_escape(self) -> None:
        """Process the escape key."""
        # Escape is designed to work backwards out of the application. If
        # the viewer is focused, the omnibox gets focused, if omnibox has
        # focus but it isn't empty, it gets emptied, if it's empty we exit
        # the application. The idea being that folk who use this often want
        # to build up muscle memory on the keyboard will know to camp on the
        # escape key until they get to where they want to be.
        if (omnibox := self.query_one(Omnibox)).has_focus:
            if omnibox.value:
                omnibox.value = ""
            else:
                self.app.exit()
        else:
            if self.query("Navigation:focus-within"):
                self.query_one(Navigation).popped_out = False
            omnibox.focus()

    def action_omnibox(self) -> None:
        """Jump to the omnibox."""
        self.query_one(Omnibox).focus()

    def action_table_of_contents(self) -> None:
        """Display and focus the table of contents pane."""
        self.query_one(Navigation).jump_to_contents()

    def action_local_files(self) -> None:
        """Display and focus the local files selection pane."""
        self.query_one(Navigation).jump_to_local_files()

    def action_bookmarks(self) -> None:
        """Display and focus the bookmarks selection pane."""
        self.query_one(Navigation).jump_to_bookmarks()

    def action_history(self) -> None:
        """Display and focus the history pane."""
        self.query_one(Navigation).jump_to_history()

    def action_backward(self) -> None:
        """Go backward in the history."""
        self.query_one(Viewer).back()

    def action_forward(self) -> None:
        """Go forward in the history."""
        self.query_one(Viewer).forward()

    def action_help(self) -> None:
        """Show the help."""
        self.app.push_screen(HelpDialog())

    def action_about(self) -> None:
        """Show the about dialog."""
        self.app.push_screen(
            InformationDialog(
                f"{APPLICATION_TITLE} [b dim]v{__version__}",
                f"Built with [@click=app.visit('{TEXTUAL_URL}')]Textual[/] "
                f"by [@click=app.visit('{ORGANISATION_URL}')]{ORGANISATION_TITLE}[/].\n\n"
                f"[@click=app.visit('https://github.com/{ORGANISATION_NAME}/{PACKAGE_NAME}')]"
                f"https://github.com/{ORGANISATION_NAME}/{PACKAGE_NAME}[/]",
            )
        )

    def add_bookmark(self, location: Path | URL, bookmark: str) -> None:
        """Handle adding the bookmark.

        Args:
            location: The location to bookmark.
            bookmark: The bookmark to add.
        """
        self.query_one(Navigation).bookmarks.add_bookmark(bookmark, location)

    def action_bookmark_this(self) -> None:
        """Add a bookmark for the currently-viewed file."""

        location = self.query_one(Viewer).location

        # Only allow bookmarking if we're actually viewing something that
        # can be bookmarked.
        if not isinstance(location, (Path, URL)):
            self.app.push_screen(
                ErrorDialog(
                    "Not a bookmarkable location",
                    "The current view can't be bookmarked.",
                )
            )
            return

        # To make a bookmark, we need a title and a location. We've got a
        # location; let's make the filename the default title.
        title = (location if isinstance(location, Path) else Path(location.path)).name

        # Give the user a chance to edit the title.
        self.app.push_screen(
            InputDialog("Bookmark title:", title),
            partial(self.add_bookmark, location),
        )

    def action_toggle_theme(self) -> None:
        """Toggle the light/dark mode theme."""
        config = load_config()
        config.light_mode = not config.light_mode
        save_config(config)
        # pylint:disable=attribute-defined-outside-init
        self.app.dark = not config.light_mode

    def action_reload(self) -> None:
        """Reload the current document."""
        self.query_one(Viewer).reload()

    def action_toggle_edit(self) -> None:
        """Toggle edit mode in the viewer (``Ctrl+E``)."""
        self.query_one(Viewer).toggle_edit()

    def action_save_file(self) -> None:
        """Save the current document (``Ctrl+S``)."""
        self.query_one(Viewer).save_file()

    def action_find(self) -> None:
        """Open the find dialog (``Ctrl+F``)."""
        self.query_one(Viewer).action_find()

    def action_goto_line(self) -> None:
        """Open the go-to-line dialog (``Ctrl+G``)."""

        def jump(line_str: str | None) -> None:
            if line_str is None:
                return
            try:
                line = int(line_str)
            except ValueError:
                self.app.notify("Invalid line number.", severity="warning")
                return
            viewer = self.query_one(Viewer)
            max_line = viewer.editor.text.count("\n") + 1
            target = max(1, min(line, max_line))
            viewer.editor.move_cursor((target - 1, 0), center=True)

        self.app.push_screen(InputDialog("Line number:"), jump)

    def action_toggle_wrap(self) -> None:
        """Toggle word wrap in the editor (``Alt+Z``)."""
        self.query_one(Viewer).toggle_wrap()

    def action_toggle_split(self) -> None:
        """Toggle split view (``Ctrl+Backslash``)."""
        self.query_one(Viewer).toggle_split()


