"""Files MCP server: read and write documents inside one folder.

Every path the model sends is untrusted. It is resolved and rejected if it
escapes the root folder (``..``, absolute paths, symlinks pointing outside).

Run standalone::

    M3ALLEMA_FILES_ROOT=./files python -m m3allema.tools.servers.files
"""

from __future__ import annotations

import os
from pathlib import Path

from mcp.server.mcpserver import MCPServer

from m3allema.tools.servers._annotations import LOCAL_WRITE, READ_ONLY

MAX_READ_BYTES = 1_000_000
MAX_READ_LINES = 400
MAX_LIST_ENTRIES = 500
MAX_SEARCH_HITS = 50


class PathOutsideRootError(ValueError):
    """A requested path points outside the allowed folder."""


def resolve_inside(root: Path, relative: str) -> Path:
    """Resolve ``relative`` against ``root`` and refuse anything outside it.

    Raises:
        PathOutsideRootError: The path escapes ``root``.

    """
    root = root.resolve()
    target = (root / relative).resolve()
    if target != root and not target.is_relative_to(root):
        raise PathOutsideRootError(f"{relative!r} is outside the workspace files folder")
    return target


def create_files_server(root: Path) -> MCPServer:
    """Build a files server confined to ``root``."""
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    server = MCPServer(
        "files",
        instructions="Read, write and search documents in the business's files folder. "
        "Paths are relative to that folder.",
    )

    def display(path: Path) -> str:
        return path.relative_to(root).as_posix() or "."

    @server.tool(annotations=READ_ONLY)
    def list_files(path: str = ".") -> str:
        """List files and folders under a folder, recursively. Folders end with '/'."""
        base = resolve_inside(root, path)
        if not base.is_dir():
            raise ValueError(f"{path!r} is not a folder")
        entries = sorted(base.rglob("*"))
        lines = [f"{display(p)}/" if p.is_dir() else display(p) for p in entries[:MAX_LIST_ENTRIES]]
        if len(entries) > MAX_LIST_ENTRIES:
            lines.append(f"... and {len(entries) - MAX_LIST_ENTRIES} more")
        return "\n".join(lines) or "(empty folder)"

    @server.tool(annotations=READ_ONLY)
    def read_file(path: str, start_line: int = 1, max_lines: int = MAX_READ_LINES) -> str:
        """Read a UTF-8 text file (CSV, Markdown, TXT, JSON...), a page of lines at a time.

        Use start_line to continue reading a long file.
        """
        target = resolve_inside(root, path)
        if not target.is_file():
            raise ValueError(f"{path!r} does not exist")
        if target.stat().st_size > MAX_READ_BYTES:
            raise ValueError(f"{path!r} is larger than {MAX_READ_BYTES // 1000} KB")
        try:
            lines = target.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError as exc:
            raise ValueError(f"{path!r} is not a text file") from exc
        start = max(start_line, 1)
        page = lines[start - 1 : start - 1 + max(1, min(max_lines, MAX_READ_LINES))]
        end = start + len(page) - 1
        text = "\n".join(page)
        if end < len(lines):
            text += f"\n\n[lines {start}-{end} of {len(lines)}; continue with start_line={end + 1}]"
        return text

    @server.tool(annotations=LOCAL_WRITE)
    def write_file(path: str, content: str, overwrite: bool = False) -> str:
        """Create a text file. Set overwrite=true to replace an existing file."""
        target = resolve_inside(root, path)
        if target.exists() and not overwrite:
            raise ValueError(f"{path!r} already exists; pass overwrite=true to replace it")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return f"Wrote {len(content)} characters to {display(target)}"

    @server.tool(annotations=READ_ONLY)
    def search_files(query: str, path: str = ".") -> str:
        """Find lines containing a phrase (case-insensitive) in text files under a folder."""
        base = resolve_inside(root, path)
        needle = query.casefold()
        hits: list[str] = []
        for file in sorted(p for p in base.rglob("*") if p.is_file()):
            if file.stat().st_size > MAX_READ_BYTES:
                continue
            try:
                lines = file.read_text(encoding="utf-8").splitlines()
            except UnicodeDecodeError:
                continue
            for number, line in enumerate(lines, start=1):
                if needle in line.casefold():
                    hits.append(f"{display(file)}:{number}: {line.strip()}")
                    if len(hits) >= MAX_SEARCH_HITS:
                        return "\n".join([*hits, "... more matches not shown"])
        return "\n".join(hits) or f"No matches for {query!r}"

    return server


if __name__ == "__main__":
    create_files_server(Path(os.environ.get("M3ALLEMA_FILES_ROOT", "."))).run("stdio")
