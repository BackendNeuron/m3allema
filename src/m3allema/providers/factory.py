"""Build providers from configuration and resolve model roles."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Literal

from m3allema.config.models import AppConfig, ProviderConfig, ProviderType
from m3allema.providers.anthropic_provider import AnthropicProvider
from m3allema.providers.base import LLMProvider
from m3allema.providers.openai_compat import OpenAICompatProvider

ProviderBuilder = Callable[[ProviderConfig], LLMProvider]

_BUILDERS: dict[ProviderType, ProviderBuilder] = {
    ProviderType.ANTHROPIC: lambda c: AnthropicProvider(
        c.api_key, base_url=c.base_url, options=dict(c.options)
    ),
    ProviderType.OPENAI_COMPAT: lambda c: OpenAICompatProvider(
        c.api_key, base_url=c.base_url, options=dict(c.options)
    ),
}

Role = Literal["main", "fast", "fallback"]


def build_provider(config: ProviderConfig) -> LLMProvider:
    """Create the adapter that matches ``config.type``."""
    return _BUILDERS[config.type](config)


@dataclass(frozen=True, slots=True)
class ResolvedModel:
    """A provider together with the model name it should use."""

    ref: str
    provider: LLMProvider
    model: str


class ModelRouter:
    """Maps roles (``main``, ``fast``, ``fallback``) to concrete models.

    Providers are created lazily and shared between roles that use the same
    provider entry, so one HTTP client serves them all.

    Args:
        config: Application configuration.
        providers: Pre-built providers by name, mainly for tests.

    """

    def __init__(
        self, config: AppConfig, *, providers: Mapping[str, LLMProvider] | None = None
    ) -> None:
        self._config = config
        self._providers: dict[str, LLMProvider] = dict(providers or {})

    def resolve(self, role: Role = "main") -> ResolvedModel | None:
        """Return the model for ``role``, or ``None`` when the role is not configured."""
        ref = getattr(self._config.models, role)
        if ref is None:
            return None
        provider_name, model = ref.split("/", 1)
        if provider_name not in self._providers:
            self._providers[provider_name] = build_provider(self._config.providers[provider_name])
        return ResolvedModel(ref=ref, provider=self._providers[provider_name], model=model)
