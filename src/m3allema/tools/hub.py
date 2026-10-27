"""The tool hub: one place that connects to every MCP server.

Built-in servers run in-process (no subprocess, instant start). External
servers from ``config.yaml`` are launched over stdio or reached over HTTP.
Every tool is exposed to the model as ``<server>__<tool>`` so names never
collide between servers.

Trust model:

* Built-in servers are part of M3allema, so their MCP annotations decide
  their risk level.
* External servers are untrusted: their tools are treated as ``external``
  (always ask) whatever their annotations claim.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from contextlib import AsyncExitStack
from dataclasses import dataclass
from types import TracebackType
from typing import Any, Self

from mcp import Client, StdioServerParameters
from mcp.server.mcpserver import MCPServer
from mcp.types import CallToolResult, ToolAnnotations

from m3allema.agent.interfaces import ToolOutput
from m3allema.config.models import McpServerConfig
from m3allema.domain.tools import Risk, ToolSpec
from m3allema.tools.servers import BUILTIN_SERVERS, ToolContext

SEPARATOR = "__"


def risk_from_annotations(annotations: ToolAnnotations | None) -> Risk:
    """Map MCP tool annotations to a risk level.

    Read-only tools are ``read``; local, non-destructive writes are ``write``;
    anything destructive, open-world or unannotated is ``external``.
    """
    if annotations is None:
        return Risk.EXTERNAL
    if annotations.read_only_hint:
        return Risk.READ
    if annotations.destructive_hint is False and annotations.open_world_hint is False:
        return Risk.WRITE
    return Risk.EXTERNAL


@dataclass(frozen=True, slots=True)
class _Route:
    client: Client
    tool: str


class ToolHub:
    """Connects to MCP servers and implements the agent's tool-executor interface.

    Use as an async context manager so every connection and subprocess is
    closed when the session ends::

        async with ToolHub.from_config(builtins, external, files_root) as hub:
            agent = Agent(tools=hub, ...)

    Args:
        builtin: Built-in servers by name (trusted, run in-process).
        external: External server configurations by name (untrusted).

    """

    def __init__(
        self,
        builtin: Mapping[str, MCPServer] | None = None,
        external: Mapping[str, McpServerConfig] | None = None,
    ) -> None:
        self._builtin = dict(builtin or {})
        self._external = dict(external or {})
        self._stack = AsyncExitStack()
        self._specs: list[ToolSpec] = []
        self._routes: dict[str, _Route] = {}

    @classmethod
    def from_config(
        cls,
        builtin_names: Sequence[str],
        external: Mapping[str, McpServerConfig],
        context: ToolContext,
    ) -> ToolHub:
        """Create a hub with the named built-in servers and the external ones.

        Raises:
            ValueError: A built-in name is unknown.
            GoogleAuthError: A Google tool is enabled but Google is not connected.

        """
        unknown = sorted(set(builtin_names) - BUILTIN_SERVERS.keys())
        if unknown:
            raise ValueError(f"unknown built-in tools: {', '.join(unknown)}")
        servers = {name: BUILTIN_SERVERS[name](context) for name in builtin_names}
        return cls(servers, external)

    async def __aenter__(self) -> Self:
        try:
            for name, server in self._builtin.items():
                await self._connect(name, Client(server), trusted=True, allow=None)
            for name, config in self._external.items():
                await self._connect(
                    name, Client(_target(config)), trusted=False, allow=config.enabled_tools
                )
        except BaseException:
            await self._stack.aclose()
            raise
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self._stack.aclose()

    def specs(self) -> Sequence[ToolSpec]:
        """Every tool from every connected server."""
        return tuple(self._specs)

    async def call(self, name: str, arguments: dict[str, Any]) -> ToolOutput:
        """Run a tool on whichever server owns it."""
        route = self._routes.get(name)
        if route is None:
            return ToolOutput(f"Unknown tool {name!r}.", is_error=True)
        result = await route.client.call_tool(route.tool, arguments)
        return ToolOutput(_result_text(result), is_error=bool(result.is_error))

    async def _connect(
        self, server: str, client: Client, *, trusted: bool, allow: Sequence[str] | None
    ) -> None:
        connected = await self._stack.enter_async_context(client)
        cursor: str | None = None
        while True:
            page = await connected.list_tools(cursor=cursor)
            for tool in page.tools:
                if allow is not None and tool.name not in allow:
                    continue
                qualified = f"{server}{SEPARATOR}{tool.name}"
                self._routes[qualified] = _Route(connected, tool.name)
                self._specs.append(
                    ToolSpec(
                        name=qualified,
                        description=tool.description or tool.title or tool.name,
                        input_schema=dict(tool.input_schema),
                        risk=risk_from_annotations(tool.annotations) if trusted else Risk.EXTERNAL,
                    )
                )
            cursor = page.next_cursor
            if not cursor:
                break


def _target(config: McpServerConfig) -> str | StdioServerParameters:
    if config.transport == "http":
        assert config.url is not None  # noqa: S101 - guaranteed by McpServerConfig validation
        return config.url
    assert config.command is not None  # noqa: S101 - guaranteed by McpServerConfig validation
    return StdioServerParameters(command=config.command, args=config.args, env=config.env or None)


def _result_text(result: CallToolResult) -> str:
    """Flatten MCP content blocks into text for the model."""
    parts: list[str] = []
    for block in result.content:
        text = getattr(block, "text", None)
        parts.append(text if isinstance(text, str) else f"[{block.type} content]")
    return "\n".join(parts) or "(no output)"
