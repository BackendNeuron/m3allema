"""Web MCP server: fetch a public web page as readable text.

Run standalone::

    python -m m3allema.tools.servers.web
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urlparse

import httpx
from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from m3allema.text import html_to_text

MAX_PAGE_CHARS = 30_000
TIMEOUT_S = 20.0
USER_AGENT = "M3allema/0.1 (+https://github.com/BackendNeuron/m3allema)"


def ensure_public_url(url: str) -> None:
    """Reject non-HTTP URLs and hosts on private or local networks.

    This stops a prompt-injected page from making the agent probe the owner's
    router, cloud metadata endpoints or other internal services.

    Raises:
        ValueError: The URL is not a public http(s) address.

    """
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("only http(s) URLs are allowed")
    try:
        infos = socket.getaddrinfo(parsed.hostname, None)
    except socket.gaierror as exc:
        raise ValueError(f"cannot resolve {parsed.hostname}") from exc
    for info in infos:
        address = ipaddress.ip_address(info[4][0])
        if not address.is_global:
            raise ValueError(f"{parsed.hostname} points to a private or local address")


def create_web_server() -> MCPServer:
    """Build the web server."""
    server = MCPServer("web", instructions="Fetch public web pages as plain text.")

    @server.tool(annotations=ToolAnnotations(read_only_hint=True, open_world_hint=True))
    async def fetch_url(url: str) -> str:
        """Download a public web page and return its readable text."""
        await asyncio.to_thread(ensure_public_url, url)
        async with httpx.AsyncClient(
            timeout=TIMEOUT_S, follow_redirects=False, headers={"User-Agent": USER_AGENT}
        ) as client:
            response = await client.get(url)
        if response.is_redirect:
            location = response.headers.get("location", "")
            return f"The page redirects to {location}. Fetch that URL if it is the one you want."
        response.raise_for_status()
        content_type = response.headers.get("content-type", "")
        text = html_to_text(response.text) if "html" in content_type else response.text
        if len(text) > MAX_PAGE_CHARS:
            text = f"{text[:MAX_PAGE_CHARS]}\n\n[page truncated]"
        return text

    return server


if __name__ == "__main__":
    create_web_server().run("stdio")
