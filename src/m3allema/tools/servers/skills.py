"""Skills MCP server: read and save procedures in the workspace's ``skills/`` folder.

Run standalone::

    M3ALLEMA_WORKSPACE=./my-business python -m m3allema.tools.servers.skills
"""

from __future__ import annotations

import os
from pathlib import Path

from mcp.server.mcpserver import MCPServer

from m3allema.tools.servers._annotations import LOCAL_WRITE, READ_ONLY
from m3allema.tools.servers._tool import tool
from m3allema.workspace.skills import Skill, SkillLibrary


def create_skills_server(workspace_root: Path) -> MCPServer:
    """Build a skills server for the workspace at ``workspace_root``."""
    library = SkillLibrary(workspace_root)
    server = MCPServer(
        "skills",
        instructions="Follow the business's written procedures for recurring jobs.",
    )

    @tool(server, annotations=READ_ONLY)
    def list_skills() -> str:
        """List the available skills and when to use each."""
        return library.index() or "No skills yet."

    @tool(server, annotations=READ_ONLY)
    def read_skill(name: str) -> str:
        """Read a skill's full steps. Do this before a task that matches its description."""
        skill = library.get(name)
        return f"# {skill.name}\n{skill.description}\n\n{skill.steps}"

    @tool(server, annotations=LOCAL_WRITE)
    def save_skill(name: str, description: str, steps: str) -> str:
        """Save a new skill after a recurring job went well, so it is done the same way next time.

        Args:
            name: Lowercase words joined by hyphens, e.g. 'monthly-sales-report'.
            description: One line saying when to use it.
            steps: Numbered Markdown steps, naming the files, tools and checks involved.

        """
        path = library.save(Skill(name, description, steps))
        return f"Saved skill {name!r} to skills/{path.name}"

    return server


if __name__ == "__main__":
    create_skills_server(Path(os.environ.get("M3ALLEMA_WORKSPACE", "."))).run()
