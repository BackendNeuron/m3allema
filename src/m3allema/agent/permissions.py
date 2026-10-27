"""The permission gate: what may run on its own and what must be approved.

This is enforced in code, outside the model's reach. Nothing the model writes,
and nothing inside an email or web page, can change which calls need approval.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol

from m3allema.domain.messages import ToolCall
from m3allema.domain.tools import Risk, ToolSpec


@dataclass(frozen=True, slots=True)
class Decision:
    """Whether a tool call may run, and why."""

    allowed: bool
    reason: str


class PermissionGate(Protocol):
    """Decides whether one tool call may run."""

    async def check(self, call: ToolCall, spec: ToolSpec) -> Decision:
        """Return the decision for ``call``."""
        ...


Approver = Callable[[ToolCall, ToolSpec], Awaitable[bool]]
"""Asks the owner about one call (CLI prompt, web button, Telegram message)."""


async def _deny_all(call: ToolCall, spec: ToolSpec) -> bool:
    return False


class RiskPolicyGate:
    """Runs calls up to a risk level on their own and asks about the rest.

    Args:
        auto_up_to: Highest risk that runs without asking. ``Risk.READ`` is the
            safe default; ``None`` asks about every call.
        approver: How to ask the owner. Without one, risky calls are declined,
            which keeps unattended runs safe.

    """

    def __init__(
        self, auto_up_to: Risk | None = Risk.READ, approver: Approver | None = None
    ) -> None:
        self._auto_up_to = auto_up_to
        self._approver = approver or _deny_all

    async def check(self, call: ToolCall, spec: ToolSpec) -> Decision:
        """Allow automatically, or ask the approver."""
        if self._auto_up_to is not None and spec.risk.rank <= self._auto_up_to.rank:
            return Decision(True, f"{spec.risk.value} tools run automatically")
        if await self._approver(call, spec):
            return Decision(True, "approved by the owner")
        return Decision(False, "declined by the owner")
