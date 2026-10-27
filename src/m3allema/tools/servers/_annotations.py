"""MCP tool annotations shared by the built-in servers.

The tool hub turns these into M3allema risk levels: read-only tools are
``read``; non-destructive changes that reach nobody else are ``write``;
anything destructive or outward-facing is ``external``.
"""

from mcp.types import ToolAnnotations

READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=False)
"""Only reads data."""

LOCAL_WRITE = ToolAnnotations(read_only_hint=False, destructive_hint=False, open_world_hint=False)
"""Creates or adds data without destroying anything or reaching other people
(a file, a draft, an appended row, archiving an email)."""

LOCAL_DESTRUCTIVE = ToolAnnotations(
    read_only_hint=False, destructive_hint=True, open_world_hint=False
)
"""May overwrite or delete data."""

OUTWARD = ToolAnnotations(read_only_hint=False, destructive_hint=False, open_world_hint=True)
"""Reaches other people (sends an email, invites attendees)."""
