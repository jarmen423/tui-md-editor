# TUI Markdown Editor

A terminal-based markdown editor built with [Textual](https://textual.textualize.io/), forked from [Frogmouth](https://github.com/Textualize/frogmouth).

It keeps all of Frogmouth's excellent navigation, history, bookmarks, and scrolling Markdown preview — and adds an integrated editor so you can edit files right in the terminal.

## Features

- **Full Frogmouth navigation** — Omnibox address bar, sidebar with bookmarks/history/local files/table of contents
- **Scrollable Markdown preview** — Proper scrolling with table of contents, link navigation, and history
- **Edit mode** — Press `Ctrl+E` to switch from preview to a syntax-highlighted TextArea editor
- **Save** — Press `Ctrl+S` to write changes back to disk
- **Dirty tracking** — Know when you have unsaved changes
- **Remote URLs** — Open Markdown files from the web (read-only)

## Installation

Install the package into your virtual environment in editable mode:

```bash
pip install -e .
```

This installs the `tui-md-editor` CLI command.

## Usage

Launch the editor with an optional starting file:

```bash
tui-md-editor
tui-md-editor ~/notes.md
```

## Keybindings

### Navigation (Frogmouth defaults)

| Key | Action |
|-----|--------|
| `/` or `:` | Focus the omnibox (address bar) |
| `Ctrl+N` | Toggle navigation sidebar |
| `Ctrl+Left` | Back in history |
| `Ctrl+Right` | Forward in history |
| `Ctrl+R` | Reload current document |
| `Ctrl+B` | Show bookmarks |
| `Ctrl+Y` | Show history |
| `Ctrl+L` | Show local files |
| `Ctrl+T` | Show table of contents |
| `F1` | Help |
| `F2` | About |
| `Ctrl+Q` | Quit |

### Editing (new)

| Key | Action |
|-----|--------|
| `Ctrl+E` | Toggle Edit / Preview mode |
| `Ctrl+S` | Save the current file |

## Project Structure

This is a fork of Frogmouth with the following modifications:

- `src/tui_md_editor/widgets/viewer.py` — Added `TextArea` editor inside a `ContentSwitcher`, plus `toggle_edit()` and `save_file()` methods
- `src/tui_md_editor/screens/main.py` — Added `Ctrl+E` and `Ctrl+S` bindings wired to the Viewer
- `src/tui_md_editor/app/app.py` — Updated entry point and branding
- `src/tui_md_editor/utility/advertising.py` — Updated app title

## Testing

```bash
pytest tests/ -v
```

## License

MIT (inherits from Frogmouth)
