"""Skills: written procedures for recurring jobs, one Markdown file each.

A skill lives in ``skills/<name>.md``::

    ---
    description: Summarise this month's invoices into an Excel workbook.
    ---
    1. List files/invoices ...

The system prompt lists every skill's name and description; the model reads
the full steps with a tool only when a task matches, so many skills cost
little context. New workspaces start with a few starter skills, the owner can
write their own, and M3allema can propose one after a job goes well. Saving
goes through a ``write`` tool, so by default the owner approves it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

SKILLS_DIR = "skills"
MAX_SKILL_CHARS = 8000
MAX_DESCRIPTION_CHARS = 200
_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{1,48}[a-z0-9]$")
_FRONT = re.compile(r"\A---\s*\n(?P<meta>.*?)\n---\s*\n?(?P<body>.*)\Z", re.DOTALL)


class SkillError(ValueError):
    """A skill could not be found or saved."""


@dataclass(frozen=True, slots=True)
class Skill:
    """One skill: its name (the file name), when to use it, and its steps."""

    name: str
    description: str
    steps: str

    def to_markdown(self) -> str:
        """Render the skill file."""
        return f"---\ndescription: {self.description}\n---\n{self.steps.strip()}\n"


def check_name(name: str) -> str:
    """Return ``name`` if it is a valid skill name (lowercase words joined by hyphens).

    Raises:
        SkillError: The name could escape the folder or is badly formed.

    """
    if not _NAME.match(name):
        raise SkillError(
            f"{name!r} is not a valid skill name: use 3-50 lowercase letters, digits and hyphens"
        )
    return name


def parse_skill(name: str, text: str) -> Skill:
    """Parse a skill file; a file without front matter uses its first line as description."""
    match = _FRONT.match(text)
    if match:
        description = ""
        for line in match["meta"].splitlines():
            key, _, value = line.partition(":")
            if key.strip() == "description":
                description = value.strip()
        return Skill(name, description, match["body"].strip())
    first, _, rest = text.strip().partition("\n")
    return Skill(name, first.lstrip("# ").strip(), rest.strip())


class SkillLibrary:
    """The skills folder of one workspace."""

    def __init__(self, root: Path) -> None:
        self._dir = root / SKILLS_DIR

    def list(self) -> list[Skill]:
        """Return every valid skill, sorted by name. Badly named files are ignored."""
        if not self._dir.is_dir():
            return []
        skills = []
        for path in sorted(self._dir.glob("*.md")):
            if _NAME.match(path.stem):
                skills.append(parse_skill(path.stem, path.read_text(encoding="utf-8")))
        return skills

    def get(self, name: str) -> Skill:
        """Load one skill.

        Raises:
            SkillError: No skill has that name.

        """
        path = self._dir / f"{check_name(name)}.md"
        if not path.is_file():
            known = ", ".join(s.name for s in self.list()) or "none"
            raise SkillError(f"no skill named {name!r} (available: {known})")
        return parse_skill(name, path.read_text(encoding="utf-8"))

    def save(self, skill: Skill, *, overwrite: bool = False) -> Path:
        """Write a skill file.

        Raises:
            SkillError: Bad name, too long, or it exists and ``overwrite`` is false.

        """
        check_name(skill.name)
        description = " ".join(skill.description.split())
        if not description or len(description) > MAX_DESCRIPTION_CHARS:
            raise SkillError(f"give a one-line description under {MAX_DESCRIPTION_CHARS} chars")
        if not skill.steps.strip() or len(skill.steps) > MAX_SKILL_CHARS:
            raise SkillError(f"steps must be between 1 and {MAX_SKILL_CHARS} characters")
        path = self._dir / f"{skill.name}.md"
        if path.exists() and not overwrite:
            raise SkillError(f"a skill named {skill.name!r} already exists")
        self._dir.mkdir(exist_ok=True)
        path.write_text(Skill(skill.name, description, skill.steps).to_markdown(), encoding="utf-8")
        return path

    def index(self) -> str:
        """One line per skill, for the system prompt."""
        return "\n".join(f"- {s.name}: {s.description}" for s in self.list())
