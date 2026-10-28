"""Long-term memory: facts M3allema keeps between conversations.

Memory is the workspace's ``MEMORY.md``, one dated bullet per fact, so the
owner can read, edit or delete anything she remembers with a text editor. It is
loaded into the system prompt like the other context files. Saving and
forgetting touch only fact lines; anything else the owner writes there is kept.

Saving a fact goes through a ``write`` tool, so with the default policy the
owner approves every new memory. That matters: memory outlives the
conversation, and an instruction hidden in an email or web page must not be
able to plant itself there silently.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

MEMORY_FILE = "MEMORY.md"
MAX_FACT_CHARS = 300
MAX_FACTS = 200
"""Beyond this the owner is asked to prune; the whole file goes into every prompt."""

_HEADER = "# Memory\n\n<!-- Facts M3allema learned. Edit or delete lines freely. -->\n\n"
_FACT = re.compile(r"^- (?:\((?P<day>\d{4}-\d{2}-\d{2})\) )?(?P<text>.+)$")


class MemoryBookError(ValueError):
    """A fact could not be saved or found, or memory is full."""


@dataclass(frozen=True, slots=True)
class Fact:
    """One remembered fact and the day it was saved."""

    text: str
    day: str = ""

    def line(self) -> str:
        """Render the fact as a ``MEMORY.md`` bullet."""
        return f"- ({self.day}) {self.text}" if self.day else f"- {self.text}"


class MemoryBook:
    """Read and change ``MEMORY.md`` in a workspace folder."""

    def __init__(self, root: Path) -> None:
        self._path = root / MEMORY_FILE

    def facts(self) -> list[Fact]:
        """Return every fact, oldest first."""
        return [fact for _, fact in self._lines() if fact is not None]

    def remember(self, text: str, today: date | None = None) -> Fact:
        """Add a fact. A fact already remembered is returned unchanged.

        Raises:
            MemoryBookError: The fact is empty or too long, or memory is full.

        """
        clean = " ".join(text.split())
        if not clean:
            raise MemoryBookError("the fact is empty")
        if len(clean) > MAX_FACT_CHARS:
            raise MemoryBookError(f"keep facts under {MAX_FACT_CHARS} characters")
        facts = self.facts()
        for fact in facts:
            if fact.text.casefold() == clean.casefold():
                return fact
        if len(facts) >= MAX_FACTS:
            raise MemoryBookError(
                f"memory is full ({MAX_FACTS} facts); ask the owner to prune {MEMORY_FILE}"
            )
        fact = Fact(clean, (today or date.today()).isoformat())
        current = self._path.read_text(encoding="utf-8") if self._path.is_file() else _HEADER
        if not current.endswith("\n"):
            current += "\n"
        self._path.write_text(current + fact.line() + "\n", encoding="utf-8")
        return fact

    def forget(self, text: str) -> list[Fact]:
        """Remove every fact containing ``text`` (case-insensitive).

        Raises:
            MemoryBookError: Nothing matched.

        """
        needle = " ".join(text.split()).casefold()
        if not needle:
            raise MemoryBookError("say which fact to forget")
        kept: list[str] = []
        removed: list[Fact] = []
        for line, fact in self._lines():
            if fact is not None and needle in fact.text.casefold():
                removed.append(fact)
            else:
                kept.append(line)
        if not removed:
            raise MemoryBookError(f"no remembered fact contains {text!r}")
        self._path.write_text("\n".join(kept) + "\n", encoding="utf-8")
        return removed

    def _lines(self) -> list[tuple[str, Fact | None]]:
        if not self._path.is_file():
            return []
        result: list[tuple[str, Fact | None]] = []
        for line in self._path.read_text(encoding="utf-8").splitlines():
            match = _FACT.match(line.strip())
            result.append((line, Fact(match["text"], match["day"] or "") if match else None))
        return result
