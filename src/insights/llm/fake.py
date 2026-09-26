"""A scripted :class:`~insights.llm.base.LLMClient` for tests.

Every test of the planner, the validator and the refusal path runs against this
rather than a real model. That is not a shortcut: a test whose result depends on
what a 7B model felt like emitting is not a test of our code, it is a test of
the model, and it fails on a Tuesday for no reason anyone can reproduce.

Whether the real model is any good is a separate question, answered by the
evaluation harness in slice 9 and by the integration test that runs only when
Ollama is actually up.
"""

from __future__ import annotations

import json
from typing import Any

from .base import LLMResponse


class FakeLLMClient:
    """Returns queued responses in order, and records what it was asked."""

    name = "fake"

    def __init__(self, responses: list[str] | None = None) -> None:
        self._responses = list(responses or [])
        #: Every (system, user) pair this client was called with, so a test can
        #: assert on what the prompt actually contained.
        self.calls: list[dict[str, Any]] = []

    def generate(
        self,
        *,
        system: str,
        user: str,
        json_schema: dict[str, Any] | None = None,
    ) -> LLMResponse:
        self.calls.append({"system": system, "user": user, "json_schema": json_schema})
        if not self._responses:
            raise AssertionError(
                "FakeLLMClient was called more times than it had responses queued"
            )
        return LLMResponse(text=self._responses.pop(0), model=self.name, duration_ms=0)

    # -- convenience constructors, so tests read as intent ------------------

    @classmethod
    def answering(cls, sql: str, reason: str = "Computes the requested figure.") -> "FakeLLMClient":
        return cls([json.dumps({"answerable": True, "sql": sql, "reason": reason})])

    @classmethod
    def refusing(cls, reason: str) -> "FakeLLMClient":
        return cls([json.dumps({"answerable": False, "sql": "", "reason": reason})])

    @classmethod
    def returning(cls, raw: str) -> "FakeLLMClient":
        """For testing what happens when the model emits something malformed."""
        return cls([raw])
