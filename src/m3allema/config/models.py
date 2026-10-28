"""Typed configuration schema.

``config.yaml`` is validated against these models when it is loaded, so a typo
fails fast with a clear message instead of surfacing later as a runtime error.
Secrets never live in this file: values written as ``env:NAME`` are resolved
from the environment (or ``.env``) by :mod:`m3allema.config.loader`.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _Strict(BaseModel):
    """Base model that rejects unknown keys, catching typos in config files."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class ProviderType(StrEnum):
    """Which adapter talks to a provider."""

    ANTHROPIC = "anthropic"
    OPENAI_COMPAT = "openai_compat"


class ProviderConfig(_Strict):
    """Connection settings for one LLM provider.

    Attributes:
        type: Adapter to use. ``openai_compat`` covers OpenAI, Groq, Gemini's
            OpenAI endpoint, Ollama, OpenRouter, vLLM and similar servers.
        api_key: The key, already resolved from ``env:NAME``. ``None`` for
            local servers such as Ollama.
        base_url: Endpoint override; required for most ``openai_compat`` servers.
        options: Adapter-specific request options (for example ``effort``).

    """

    type: ProviderType
    api_key: str | None = None
    base_url: str | None = None
    options: dict[str, Any] = Field(default_factory=dict)


class ModelRoles(_Strict):
    """Which ``provider/model`` plays each role.

    Roles let owners swap models without touching code: the expensive model
    plans, a cheap one handles bulk steps, a local one is the fallback.
    """

    main: str
    fast: str | None = None
    fallback: str | None = None

    @model_validator(mode="after")
    def _check_format(self) -> ModelRoles:
        for role in ("main", "fast", "fallback"):
            ref = getattr(self, role)
            if ref is not None and "/" not in ref:
                raise ValueError(f"models.{role} must look like 'provider/model', got {ref!r}")
        return self


class McpServerConfig(_Strict):
    """An external MCP server to connect to.

    Attributes:
        transport: ``stdio`` launches ``command`` locally; ``http`` connects to ``url``.
        enabled_tools: Optional allowlist; when set, other tools are hidden.

    """

    transport: Literal["stdio", "http"]
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    url: str | None = None
    enabled_tools: list[str] | None = None

    @model_validator(mode="after")
    def _check_transport(self) -> McpServerConfig:
        if self.transport == "stdio" and not self.command:
            raise ValueError("stdio MCP servers need a 'command'")
        if self.transport == "http" and not self.url:
            raise ValueError("http MCP servers need a 'url'")
        return self


class AgentSettings(_Strict):
    """Limits for the agent loop."""

    max_steps: int = Field(default=25, ge=1, le=200)
    max_tokens: int = Field(default=16_000, ge=256)
    tool_timeout_s: float = Field(default=60.0, gt=0)


class Price(_Strict):
    """Token prices in USD per million tokens, for models not priced by default.

    Cache prices default to 10% (read) and 125% (write) of the input price.
    """

    input: float = Field(ge=0)
    output: float = Field(ge=0)
    cache_read: float | None = Field(default=None, ge=0)
    cache_write: float | None = Field(default=None, ge=0)


class StorageSettings(_Strict):
    """Where runs and events are stored.

    ``url`` is a SQLAlchemy URL. The default SQLite file lives inside the
    workspace; Docker deployments point it at Postgres instead.
    """

    url: str | None = None


class AppConfig(_Strict):
    """The whole of ``config.yaml``."""

    providers: dict[str, ProviderConfig]
    models: ModelRoles
    agent: AgentSettings = Field(default_factory=AgentSettings)
    storage: StorageSettings = Field(default_factory=StorageSettings)
    mcp_servers: dict[str, McpServerConfig] = Field(default_factory=dict)
    builtin_tools: list[str] = Field(
        default_factory=lambda: ["files", "excel", "docs", "web", "memory", "skills"]
    )
    pricing: dict[str, Price] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_model_providers(self) -> AppConfig:
        for ref in (self.models.main, self.models.fast, self.models.fallback):
            if ref is None:
                continue
            provider = ref.split("/", 1)[0]
            if provider not in self.providers:
                known = ", ".join(sorted(self.providers)) or "none"
                raise ValueError(
                    f"model {ref!r} uses unknown provider {provider!r} (known: {known})"
                )
        return self
