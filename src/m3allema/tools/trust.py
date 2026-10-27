"""Pin what external MCP tools say they do, and hide them when that changes.

A malicious or compromised MCP server can change a tool's description to slip
instructions to the model ("tool poisoning"), or add new tools after the owner
reviewed it. M3allema keeps a fingerprint of every external tool the owner has
approved. New tools and tools whose name, description or input schema changed
are hidden from the model until the owner approves them again with
``m3allema mcp trust <server>``.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any


class TrustStatus(StrEnum):
    """How an external tool compares with what the owner approved."""

    TRUSTED = "trusted"
    NEW = "new"
    CHANGED = "changed"


@dataclass(frozen=True, slots=True)
class PendingTool:
    """An external tool hidden until the owner approves it."""

    server: str
    name: str
    description: str
    status: TrustStatus


def fingerprint(name: str, description: str, input_schema: Mapping[str, Any]) -> str:
    """Stable hash of everything the model would see about a tool."""
    canonical = json.dumps(
        {"name": name, "description": description, "input_schema": input_schema},
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class ToolTrustStore:
    """Approved tool fingerprints, per server, saved as JSON in the workspace.

    Args:
        path: The JSON file, usually ``.m3allema/mcp_trust.json``.

    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._data: dict[str, dict[str, str]] = self._read()

    def status(self, server: str, tool: str, print_: str) -> TrustStatus:
        """Compare a tool's current fingerprint with the approved one."""
        approved = self._data.get(server, {}).get(tool)
        if approved is None:
            return TrustStatus.NEW
        return TrustStatus.TRUSTED if approved == print_ else TrustStatus.CHANGED

    def trust(self, server: str, prints: Mapping[str, str]) -> None:
        """Approve exactly these tools for ``server``, replacing earlier approvals."""
        self._data[server] = dict(prints)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self._data, indent=2, sort_keys=True), encoding="utf-8")

    def _read(self) -> dict[str, dict[str, str]]:
        if not self._path.is_file():
            return {}
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}
