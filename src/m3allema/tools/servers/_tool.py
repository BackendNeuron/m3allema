"""Register built-in tools so the model sees why a call failed.

The MCP SDK only passes the message of a ``ToolError`` to the model; any other
exception is reported as a bare "Error executing tool" and logged as a crash.
Our tools signal expected problems ("outside the files folder", "already
exists", "only .docx and .pdf") with ordinary exceptions, so this decorator
turns those into ``ToolError`` and lets the model correct itself. Genuine bugs
(any other exception type) still surface as crashes.
"""

from __future__ import annotations

import functools
import inspect
from collections.abc import Callable
from typing import Any, TypeVar

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

F = TypeVar("F", bound=Callable[..., Any])

EXPECTED_ERRORS: tuple[type[Exception], ...] = (ValueError, OSError, LookupError)
"""Failures caused by the request (bad path, missing file, unknown sheet), not by a bug."""


def tool(server: MCPServer, *, annotations: ToolAnnotations) -> Callable[[F], F]:
    """Register ``fn`` as a tool of ``server``, reporting expected failures to the model."""

    def register(fn: F) -> F:
        if inspect.iscoroutinefunction(fn):

            @functools.wraps(fn)
            async def run_async(*args: Any, **kwargs: Any) -> Any:
                try:
                    return await fn(*args, **kwargs)
                except EXPECTED_ERRORS as exc:
                    raise ToolError(str(exc)) from exc

            server.tool(annotations=annotations)(run_async)
        else:

            @functools.wraps(fn)
            def run(*args: Any, **kwargs: Any) -> Any:
                try:
                    return fn(*args, **kwargs)
                except EXPECTED_ERRORS as exc:
                    raise ToolError(str(exc)) from exc

            server.tool(annotations=annotations)(run)
        return fn

    return register
