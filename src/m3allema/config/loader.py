"""Load ``config.yaml`` and resolve ``env:NAME`` secret references."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import ValidationError

from m3allema.config.models import AppConfig

ENV_PREFIX = "env:"


class ConfigError(Exception):
    """The configuration file is missing, malformed or refers to unset secrets."""


def resolve_env_refs(value: Any, environ: Mapping[str, str]) -> Any:
    """Replace every ``env:NAME`` string in a nested structure with its value.

    Args:
        value: Parsed YAML (dicts, lists and scalars).
        environ: Where to look variables up, usually ``os.environ``.

    Returns:
        The same structure with references substituted.

    Raises:
        ConfigError: A referenced variable is not set.

    """
    if isinstance(value, str) and value.startswith(ENV_PREFIX):
        name = value[len(ENV_PREFIX) :]
        if name not in environ:
            raise ConfigError(f"environment variable {name} is not set (referenced as {value!r})")
        return environ[name]
    if isinstance(value, dict):
        return {key: resolve_env_refs(item, environ) for key, item in value.items()}
    if isinstance(value, list):
        return [resolve_env_refs(item, environ) for item in value]
    return value


def load_config(path: Path, *, environ: Mapping[str, str] | None = None) -> AppConfig:
    """Read, resolve and validate a configuration file.

    A ``.env`` file next to the config is loaded first (without overriding
    variables that are already set), so secrets can live there.

    Args:
        path: Location of ``config.yaml``.
        environ: Variables to resolve against; defaults to the process environment.

    Raises:
        ConfigError: The file is missing, is not valid YAML, references an
            unset variable, or does not match the schema.

    """
    if not path.is_file():
        raise ConfigError(f"config file not found: {path}")

    if environ is None:
        load_dotenv(path.parent / ".env", override=False)
        environ = os.environ

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path} is not valid YAML: {exc}") from exc

    if not isinstance(raw, dict):
        raise ConfigError(f"{path} must contain a mapping at the top level")

    try:
        return AppConfig.model_validate(resolve_env_refs(raw, environ))
    except ValidationError as exc:
        raise ConfigError(f"{path} is invalid:\n{exc}") from exc
