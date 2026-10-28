"""Built-in tool servers.

Each one is a standalone MCP server: M3allema loads them in-process, and any
MCP app (Claude Desktop, Claude Code, Cursor) can run the local ones on their
own with ``python -m m3allema.tools.servers.<name>``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

from google.oauth2.credentials import Credentials
from mcp.server.mcpserver import MCPServer

from m3allema.integrations.google.auth import GoogleAuth, GoogleAuthError
from m3allema.integrations.google.gateways import GoogleCalendar, GoogleGmail, GoogleSheets
from m3allema.tools.servers.calendar import create_calendar_server
from m3allema.tools.servers.docs import create_docs_server
from m3allema.tools.servers.excel import create_excel_server
from m3allema.tools.servers.files import create_files_server
from m3allema.tools.servers.gmail import create_gmail_server
from m3allema.tools.servers.memory import create_memory_server
from m3allema.tools.servers.sheets import create_sheets_server
from m3allema.tools.servers.shell import create_shell_server
from m3allema.tools.servers.skills import create_skills_server
from m3allema.tools.servers.web import create_web_server


@dataclass
class ToolContext:
    """What built-in servers may need from the workspace.

    Args:
        files_root: The only folder local file tools may touch.
        google: Google sign-in, or ``None`` when Google tools are not available.
        workspace_root: The workspace folder, for memory and skills. Defaults
            to the parent of ``files_root``.

    """

    files_root: Path
    google: GoogleAuth | None = None
    workspace_root: Path | None = None

    @property
    def root(self) -> Path:
        """The workspace folder."""
        return self.workspace_root or self.files_root.parent

    @cached_property
    def google_credentials(self) -> Credentials:
        """Fresh Google credentials, loaded once per session.

        Raises:
            GoogleAuthError: Google is not connected.

        """
        if self.google is None:
            raise GoogleAuthError("Google is not available in this workspace")
        return self.google.credentials()


ServerFactory = Callable[[ToolContext], MCPServer]

BUILTIN_SERVERS: dict[str, ServerFactory] = {
    "files": lambda ctx: create_files_server(ctx.files_root),
    "excel": lambda ctx: create_excel_server(ctx.files_root),
    "docs": lambda ctx: create_docs_server(ctx.files_root),
    "web": lambda _ctx: create_web_server(),
    "shell": lambda ctx: create_shell_server(ctx.files_root),
    "gmail": lambda ctx: create_gmail_server(GoogleGmail(ctx.google_credentials)),
    "calendar": lambda ctx: create_calendar_server(GoogleCalendar(ctx.google_credentials)),
    "sheets": lambda ctx: create_sheets_server(GoogleSheets(ctx.google_credentials)),
    "memory": lambda ctx: create_memory_server(ctx.root),
    "skills": lambda ctx: create_skills_server(ctx.root),
}
"""Built-in servers by name."""

GOOGLE_SERVERS = frozenset({"gmail", "calendar", "sheets"})

__all__ = [
    "BUILTIN_SERVERS",
    "GOOGLE_SERVERS",
    "ServerFactory",
    "ToolContext",
]
