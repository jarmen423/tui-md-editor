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
- **Edit any text file** — `.txt`, `.py`, `.json`, `.yaml`, and many more open as editable plain text
- **Create files & directories** — Type a non-existent path into the omnibox to create it
- **New file** — Press `:new` or `Ctrl+Shift+N` for an untitled buffer
- **Find in file** — `Ctrl+F` to search and jump to matches
- **Go to line** — `Ctrl+G` for quick line navigation
- **Word wrap** — `Alt+Z` toggles soft wrap
- **Split view** — `Ctrl+\` shows editor and preview side-by-side
- **Status bar** — Shows filename, dirty state, file type, cursor position, and word count
- **Markdown formatting shortcuts** — `Ctrl+B` bold, `Ctrl+I` italic, `Ctrl+K` code, `Ctrl+Shift+L` bullets, `Ctrl+Shift+O` numbered lists, `Ctrl+1..6` headers
- **Auto-save** — Optional automatic saving every 30 seconds
- **Starts in CWD** — Launch without a file and the sidebar opens to your current directory
- **Fuzzy file search** — Type in the omnibox and a dropdown of matching files appears after a brief pause
- **Export to HTML** — `:export html <path>` exports rendered markdown

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
| `Ctrl+Shift+E` | Show file explorer sidebar |
| `Ctrl+T` | Show table of contents |
| `F1` | Help |
| `F2` | About |
| `Ctrl+Q` | Quit |

### Editing (new)

| Key | Action |
|-----|--------|
| `Ctrl+E` | Toggle Edit / Preview mode |
| `Ctrl+S` | Save the current file |
| `Ctrl+F` | Find text in the editor |
| `Ctrl+G` | Go to line number |
| `Alt+Z` | Toggle word wrap |
| `Ctrl+\` | Toggle split view (editor + preview side-by-side) |
| `Ctrl+B` | **Bold** selection (markdown files, edit mode) |
| `Ctrl+I` | *Italic* selection (markdown files, edit mode) |
| `Ctrl+K` | `Code` selection (markdown files, edit mode) |
| `Ctrl+Shift+L` | Insert bullet list (markdown files, edit mode) |
| `Ctrl+Shift+O` | Insert numbered list (markdown files, edit mode) |
| `Ctrl+1` … `Ctrl+6` | Insert H1 … H6 (markdown files, edit mode) |

### Omnibox commands

Press `/` then type any command:

| Command | Description |
|---------|-------------|
| `new` | Open a new untitled file |
| `export html <path>` | Export current markdown to HTML |

## Project Structure

This is a fork of Frogmouth with the following modifications:

- `src/tui_md_editor/widgets/viewer.py` — Added `TextArea` editor inside a `ContentSwitcher`, plus `toggle_edit()`, `save_file()`, `toggle_split()`, `find_text()`, `new_file()`, syntax highlighting, auto-save, and markdown formatting shortcuts
- `src/tui_md_editor/widgets/status_bar.py` — New status bar showing file info, cursor position, and word count
- `src/tui_md_editor/widgets/omnibox.py` — Added `new` and `export` commands, creation of non-existent paths, and fuzzy file suggestion dropdown
- `src/tui_md_editor/screens/main.py` — Added keybindings and actions for find, go-to-line, word wrap, split view, status bar updates, `Ctrl+Shift+E` shortcut, and CWD startup behavior
- `src/tui_md_editor/utility/type_tests.py` — Added `is_text_file()` and `language_for_path()` for editing any text file
- `src/tui_md_editor/data/config.py` — Added `auto_save` and `auto_save_interval` options
- `src/tui_md_editor/dialogs/find_dialog.py` — New modal find dialog

## Testing

```bash
pytest tests/ -v
```

## License

MIT (inherits from Frogmouth)
