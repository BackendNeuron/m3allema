"""Tool descriptions shared by the agent, the providers and the permission gate."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class Risk(StrEnum):
    """How much harm a tool can do, from least to most.

    The permission gate decides per risk level whether a call runs on its own
    or waits for the owner's approval.
    """

    READ = "read"
    """Only looks at data (read a file, list emails)."""

    WRITE = "write"
    """Changes local or draft state that can be reviewed (write a file, draft an email)."""

    EXTERNAL = "external"
    """Has effects outside the business's control (send, pay, delete, post)."""

    @property
    def rank(self) -> int:
        """Ordering index, so risks can be compared."""
        return list(Risk).index(self)


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """Everything a model needs to call a tool, plus M3allema's risk metadata.

    Attributes:
        name: Unique, fully qualified name (``<server>__<tool>``).
        description: What the tool does, written for the model.
        input_schema: JSON Schema of the arguments object.
        risk: Declared risk level, used by the permission gate.

    """

    name: str
    description: str
    input_schema: dict[str, Any] = field(default_factory=lambda: {"type": "object"})
    risk: Risk = Risk.EXTERNAL
