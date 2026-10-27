"""Sandboxed shell MCP server: run commands in a throwaway Docker container.

The container has no network, limited memory and CPU, runs as an unprivileged
user, and sees only the workspace ``files/`` folder (mounted at ``/workspace``).
It is removed after every command. Docker Desktop (or Docker Engine) must be
running; otherwise the tool explains how to start it.

Run standalone::

    M3ALLEMA_FILES_ROOT=./files python -m m3allema.tools.servers.shell
"""

from __future__ import annotations

import asyncio
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from mcp.server.mcpserver import MCPServer

from m3allema.tools.servers._annotations import LOCAL_DESTRUCTIVE

DEFAULT_IMAGE = "python:3.11-slim"
TIMEOUT_S = 60.0
MAX_OUTPUT_CHARS = 20_000


@dataclass(frozen=True, slots=True)
class SandboxSettings:
    """Limits for the sandbox container."""

    image: str = DEFAULT_IMAGE
    memory: str = "512m"
    cpus: str = "1"
    timeout_s: float = TIMEOUT_S


def docker_command(root: Path, command: str, settings: SandboxSettings) -> list[str]:
    """Build the ``docker run`` argument list for one sandboxed command."""
    return [
        "docker",
        "run",
        "--rm",
        "--network",
        "none",
        "--memory",
        settings.memory,
        "--cpus",
        settings.cpus,
        "--pids-limit",
        "256",
        "--security-opt",
        "no-new-privileges",
        "--cap-drop",
        "ALL",
        "--user",
        "1000:1000",
        "--volume",
        f"{root.resolve()}:/workspace",
        "--workdir",
        "/workspace",
        settings.image,
        "sh",
        "-c",
        command,
    ]


async def run_sandboxed(root: Path, command: str, settings: SandboxSettings) -> str:
    """Run ``command`` in the sandbox and return exit code and output.

    Raises:
        RuntimeError: Docker is missing or not running, or the command timed out.

    """
    if shutil.which("docker") is None:
        raise RuntimeError("Docker is not installed. Install Docker Desktop to use the shell tool.")
    process = await asyncio.create_subprocess_exec(
        *docker_command(root, command, settings),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        output, _ = await asyncio.wait_for(process.communicate(), timeout=settings.timeout_s)
    except TimeoutError as exc:
        process.kill()
        raise RuntimeError(f"the command did not finish within {settings.timeout_s:.0f}s") from exc
    text = output.decode("utf-8", errors="replace")
    if process.returncode == 125 and "docker" in text.lower() and "daemon" in text.lower():
        raise RuntimeError("Docker is not running. Start Docker Desktop and try again.")
    if len(text) > MAX_OUTPUT_CHARS:
        text = f"{text[:MAX_OUTPUT_CHARS]}\n[output truncated]"
    return f"exit code {process.returncode}\n{text}".rstrip()


def create_shell_server(root: Path, settings: SandboxSettings | None = None) -> MCPServer:
    """Build a shell server whose commands only see ``root``."""
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    sandbox = settings or SandboxSettings()
    server = MCPServer(
        "shell",
        instructions="Run shell commands (including python) in an isolated container with no "
        "network. The working directory /workspace is the business's files folder.",
    )

    @server.tool(annotations=LOCAL_DESTRUCTIVE)
    async def run_command(command: str) -> str:
        """Run a shell command in a sandbox with no network; /workspace is the files folder.

        Python 3.11 is available, for example: python -c "print(1 + 1)".
        """
        return await run_sandboxed(root, command, sandbox)

    return server


if __name__ == "__main__":
    create_shell_server(Path(os.environ.get("M3ALLEMA_FILES_ROOT", "."))).run("stdio")
