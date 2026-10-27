"""Built-in tool servers.

Each one is a standalone MCP server: M3allema loads them in-process, and any
MCP app (Claude Desktop, Claude Code, Cursor) can run them on their own with
``python -m m3allema.tools.servers.<name>``.
"""

from collections.abc import Callable
from pathlib import Path

from mcp.server.mcpserver import MCPServer

from m3allema.tools.servers.files import create_files_server
from m3allema.tools.servers.web import create_web_server

ServerFactory = Callable[[Path], MCPServer]

BUILTIN_SERVERS: dict[str, ServerFactory] = {
    "files": create_files_server,
    "web": lambda _root: create_web_server(),
}
"""Built-in servers by name. Each factory receives the workspace ``files/`` folder."""

__all__ = ["BUILTIN_SERVERS", "ServerFactory", "create_files_server", "create_web_server"]
