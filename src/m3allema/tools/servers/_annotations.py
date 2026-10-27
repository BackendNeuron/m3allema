"""MCP tool annotations shared by the built-in servers.

The tool hub turns these into M3allema risk levels: read-only tools are
``read``; local, non-destructive writes are ``write``; anything else is ``external``.
"""

from mcp.types import ToolAnnotations

READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=False)
"""Only reads local data."""

LOCAL_WRITE = ToolAnnotations(read_only_hint=False, destructive_hint=False, open_world_hint=False)
"""Creates or adds to local files without destroying anything."""

LOCAL_DESTRUCTIVE = ToolAnnotations(
    read_only_hint=False, destructive_hint=True, open_world_hint=False
)
"""May change or delete local files."""
