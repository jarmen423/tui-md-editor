"""Typst compile worker, run as ``python -m tui_md_editor.utility.typeset_worker``.

Started by :class:`tui_md_editor.utility.typeset.TypesetRenderer`. It's a
separate process because Typst holds the GIL while compiling, and it's a
plain subprocess (not :mod:`multiprocessing`) so it never re-imports the
app, which would probe the terminal while Textual owns it.

Protocol, over stdin/stdout:
    - request: 4-byte big-endian length, then UTF-8 JSON
      ``{"source": str, "root": str, "ppi": float}``
    - response: 1 status byte (0 = PNG follows, 1 = error message follows),
      4-byte big-endian length, then the payload
"""

from __future__ import annotations

import json
import sys


def main() -> None:
    """Serve compile requests until stdin closes."""
    import typst  # pylint: disable=import-outside-toplevel

    compiler = typst.Compiler()
    requests = sys.stdin.buffer
    responses = sys.stdout.buffer
    while len(header := requests.read(4)) == 4:
        request = json.loads(requests.read(int.from_bytes(header, "big")))
        try:
            result = compiler.compile(
                input=request["source"].encode("utf-8"),
                root=request["root"],
                format="png",
                ppi=request["ppi"],
            )
        except Exception as error:  # pylint: disable=broad-exception-caught
            status = 1
            payload = str(getattr(error, "message", None) or error).encode("utf-8")
        else:
            status = 0
            # A height: auto page only splits on explicit page breaks, which
            # Markdown can't produce; keep the first page if it ever happens.
            payload = (result[0] if isinstance(result, list) else result) or b""
        responses.write(bytes([status]) + len(payload).to_bytes(4, "big") + payload)
        responses.flush()


if __name__ == "__main__":
    main()
