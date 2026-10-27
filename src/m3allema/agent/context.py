"""Keep the model's context small without rewriting history.

Editing earlier turns would invalidate prompt caches and, for Claude, the
thinking blocks tied to that history. So nothing already sent is ever changed.
Instead, large tool outputs are trimmed *before* they enter the conversation:
the full text is saved to a file and the model gets the beginning plus a note
telling it where to read the rest, a page at a time.
"""

from __future__ import annotations

import re
from pathlib import Path

DEFAULT_INLINE_CHARS = 8_000
"""Tool output longer than this is moved to a file."""


class OutputArchive:
    """Saves oversized tool outputs where the files tools can page through them.

    Args:
        directory: Folder for saved outputs; must be inside the files tools' root.
        files_root: The files tools' root, used to show the model a relative path.
        inline_chars: How much output stays inline in the conversation.

    """

    def __init__(
        self, directory: Path, files_root: Path, inline_chars: int = DEFAULT_INLINE_CHARS
    ) -> None:
        self._directory = directory
        self._files_root = files_root
        self._inline_chars = inline_chars

    def fit(self, call_id: str, tool: str, content: str) -> str:
        """Return ``content`` unchanged if small, else a preview pointing to the saved file."""
        if len(content) <= self._inline_chars:
            return content
        self._directory.mkdir(parents=True, exist_ok=True)
        safe_id = re.sub(r"[^A-Za-z0-9_-]", "_", call_id)[:64]
        path = self._directory / f"{tool}-{safe_id}.txt"
        path.write_text(content, encoding="utf-8")
        relative = path.relative_to(self._files_root).as_posix()
        lines = content.count("\n") + 1
        return (
            f"{content[: self._inline_chars]}\n\n"
            f"[Output truncated: {len(content):,} characters, {lines:,} lines. The full output "
            f"is saved as {relative!r}; read more with files__read_file using start_line.]"
        )
