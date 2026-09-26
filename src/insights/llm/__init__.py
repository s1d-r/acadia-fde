"""LLM clients, and the one place that decides which to build."""

from __future__ import annotations

from ..config import Settings, get_settings
from ..errors import InsightsError
from .base import LLMClient, LLMResponse
from .fake import FakeLLMClient
from .ollama import OllamaClient

__all__ = [
    "FakeLLMClient",
    "LLMClient",
    "LLMResponse",
    "OllamaClient",
    "build_client",
]


class UnknownProvider(InsightsError):
    code = "unknown_llm_provider"
    http_status = 500


#: Provider name -> how to build it. A new provider is one entry here and one
#: file next to this one; nothing that reasons about questions changes.
_PROVIDERS = {
    "ollama": OllamaClient,
}


def build_client(*, settings: Settings | None = None) -> LLMClient:
    """Build the configured client."""
    settings = settings or get_settings()
    try:
        factory = _PROVIDERS[settings.llm_provider]
    except KeyError:
        raise UnknownProvider(
            f"No LLM provider named {settings.llm_provider!r}",
            details={"known": sorted(_PROVIDERS)},
        ) from None
    return factory(settings=settings)
