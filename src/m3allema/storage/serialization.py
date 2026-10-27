"""Turn agent events into JSON-friendly records for the event log."""

from __future__ import annotations

import dataclasses
from enum import Enum
from typing import Any

from m3allema.domain.events import AgentEvent


def _jsonable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: _jsonable(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(v) for v in value]
    return value


def event_kind(event: AgentEvent) -> str:
    """Stable snake_case name for an event type, e.g. ``tool_call_started``."""
    name = type(event).__name__
    return "".join(f"_{c.lower()}" if c.isupper() else c for c in name).lstrip("_")


def event_to_payload(event: AgentEvent) -> dict[str, Any]:
    """Serialize an event to a JSON-compatible dict."""
    payload: dict[str, Any] = _jsonable(event)
    return payload
