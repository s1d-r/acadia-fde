"""An :class:`~insights.llm.base.LLMClient` backed by a local Ollama server.

Chosen because it runs on the machine doing the demo: no API key, no network,
no per-question cost, and nothing to fail in a room with bad wifi. The trade is
a 7B model rather than a frontier one, which is why the validator and the
refusal path carry more weight here than they would behind a large model.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from ..config import Settings, get_settings
from ..errors import LLMUnavailable
from .base import LLMResponse


class OllamaClient:
    """Talks to Ollama's ``/api/chat`` endpoint."""

    def __init__(self, *, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self.name = self._settings.ollama_model

    def generate(
        self,
        *,
        system: str,
        user: str,
        json_schema: dict[str, Any] | None = None,
    ) -> LLMResponse:
        payload: dict[str, Any] = {
            "model": self._settings.ollama_model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            # One response, not a stream. The caller has nothing to do with a
            # half-written SQL statement.
            "stream": False,
            "options": {
                # Temperature zero: the same question against the same data
                # should produce the same SQL. Not guaranteed - sampling is not
                # the only source of variation - but the one source we can
                # remove for free.
                "temperature": self._settings.llm_temperature,
                "num_ctx": self._settings.llm_context_tokens,
            },
        }
        if json_schema is not None:
            # Ollama constrains decoding to the schema, so the model cannot
            # emit prose around the JSON. We still parse defensively.
            payload["format"] = json_schema

        started = time.perf_counter()
        try:
            response = httpx.post(
                f"{self._settings.ollama_host}/api/chat",
                json=payload,
                timeout=self._settings.llm_timeout_seconds,
            )
            response.raise_for_status()
            body = response.json()
        except httpx.TimeoutException as exc:
            raise LLMUnavailable(
                "The model did not respond in time",
                details={
                    "model": self._settings.ollama_model,
                    "timeout_seconds": self._settings.llm_timeout_seconds,
                },
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise LLMUnavailable(
                "The model server rejected the request",
                details={
                    "model": self._settings.ollama_model,
                    "status": exc.response.status_code,
                },
            ) from exc
        except httpx.HTTPError as exc:
            raise LLMUnavailable(
                "The model server could not be reached",
                details={"host": self._settings.ollama_host},
            ) from exc

        duration_ms = int((time.perf_counter() - started) * 1000)
        text = body.get("message", {}).get("content", "")
        if not text:
            raise LLMUnavailable(
                "The model returned an empty response",
                details={"model": self._settings.ollama_model},
            )

        return LLMResponse(
            text=text, model=self._settings.ollama_model, duration_ms=duration_ms
        )
