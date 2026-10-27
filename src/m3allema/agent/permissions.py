"""The permission gate: what may run on its own and what must be approved.

This is enforced in code, outside the model's reach. Nothing the model writes,
and nothing inside an email or web page, can change which calls need approval.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol

from m3allema.config.policy import Mode, Policy
from m3allema.domain.messages import ToolCall
from m3allema.domain.tools import ToolSpec


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


class PolicyGate:
    """Applies ``policy.yaml``: run, ask the owner, or refuse.

    Args:
        policy: The workspace policy. Defaults to the safe policy (only reads run alone).
        approver: How to ask the owner. Without one, ``ask`` calls are declined,
            which keeps unattended runs safe.

    """

    def __init__(self, policy: Policy | None = None, approver: Approver | None = None) -> None:
        self._policy = policy or Policy()
        self._approver = approver

    async def check(self, call: ToolCall, spec: ToolSpec) -> Decision:
        """Decide according to the policy, asking the approver for ``ask`` tools."""
        mode = self._policy.mode_for(spec)
        if mode is Mode.AUTO:
            return Decision(True, "allowed by policy")
        if mode is Mode.DENY:
            return Decision(False, "blocked by the workspace policy")
        if self._approver is None:
            return Decision(False, "needs approval and nobody is available to approve")
        if await self._approver(call, spec):
            return Decision(True, "approved by the owner")
        return Decision(False, "declined by the owner")
