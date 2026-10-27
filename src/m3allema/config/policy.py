"""``policy.yaml``: what M3allema may do on her own, what she must ask about, what she may never do.

Example::

    defaults:          # by risk level
      read: auto
      write: ask
      external: ask
    tools:             # per-tool overrides; shell-style patterns, first match wins
      "web__*": auto
      "files__write_file": auto
      "gmail__delete_*": deny
    budget:
      per_run_usd: 0.50
      per_day_usd: 5.00

Unlike the markdown files, this is enforced in code by the permission gate and
the budget guard. A missing file means the safe defaults below.
"""

from __future__ import annotations

from enum import StrEnum
from fnmatch import fnmatchcase
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from m3allema.config.loader import ConfigError
from m3allema.domain.tools import Risk, ToolSpec


class Mode(StrEnum):
    """What happens when a tool is called."""

    AUTO = "auto"
    """Runs without asking."""

    ASK = "ask"
    """Waits for the owner's approval."""

    DENY = "deny"
    """Never runs."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RiskDefaults(_Strict):
    """Mode per risk level. Safe by default: only reading runs on its own."""

    read: Mode = Mode.AUTO
    write: Mode = Mode.ASK
    external: Mode = Mode.ASK

    def for_risk(self, risk: Risk) -> Mode:
        """Return the mode for ``risk``."""
        mode: Mode = getattr(self, risk.value)
        return mode


class Budget(_Strict):
    """Spending limits in US dollars. ``None`` means no limit."""

    per_run_usd: float | None = Field(default=None, gt=0)
    per_day_usd: float | None = Field(default=None, gt=0)


class Policy(_Strict):
    """The whole of ``policy.yaml``."""

    defaults: RiskDefaults = Field(default_factory=RiskDefaults)
    tools: dict[str, Mode] = Field(default_factory=dict)
    budget: Budget = Field(default_factory=Budget)

    def mode_for(self, spec: ToolSpec) -> Mode:
        """Resolve the mode for a tool: the first matching pattern, else its risk default."""
        for pattern, mode in self.tools.items():
            if fnmatchcase(spec.name, pattern):
                return mode
        return self.defaults.for_risk(spec.risk)


def load_policy(path: Path) -> Policy:
    """Read ``policy.yaml``; return the safe defaults when the file does not exist.

    Raises:
        ConfigError: The file exists but is invalid.

    """
    if not path.is_file():
        return Policy()
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return Policy.model_validate(raw)
    except (yaml.YAMLError, ValidationError) as exc:
        raise ConfigError(f"{path} is invalid:\n{exc}") from exc
