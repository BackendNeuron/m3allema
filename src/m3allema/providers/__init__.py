"""LLM providers behind one interface.

Two adapters cover the field:

* :class:`AnthropicProvider` - Claude through the official SDK, keeping every
  native feature (prompt caching, adaptive thinking, refusal fallbacks).
* :class:`OpenAICompatProvider` - anything that speaks the OpenAI Chat
  Completions API: OpenAI, Groq, Gemini's compatible endpoint, Ollama,
  OpenRouter, vLLM and others.
"""

from m3allema.providers.anthropic_provider import AnthropicProvider
from m3allema.providers.base import CompletionRequest, LLMProvider, ProviderError
from m3allema.providers.factory import ModelRouter, ResolvedModel, build_provider
from m3allema.providers.openai_compat import OpenAICompatProvider

__all__ = [
    "AnthropicProvider",
    "CompletionRequest",
    "LLMProvider",
    "ModelRouter",
    "OpenAICompatProvider",
    "ProviderError",
    "ResolvedModel",
    "build_provider",
]
