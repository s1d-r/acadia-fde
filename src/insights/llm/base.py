"""The boundary between this system and a language model.

One method, one return type. Everything above this line - the planner, the
prompts, the refusal handling - is written against this protocol and has never
heard of Ollama, or of any other provider.

That is the whole point. Swapping the model provider is a new file next to this
one and a changed setting, not a change to anything that reasons about
questions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class LLMResponse:
    """What a model returned, and what it cost to get it."""

    text: str
    model: str
    duration_ms: int


@runtime_checkable
class LLMClient(Protocol):
    """A single-turn text generator that can be asked for JSON.

    Deliberately not a chat interface. Planning a question is one exchange with
    no history: the schema context and the question go in, a decision comes
    back. A conversational interface would invite state we do not have and
    cannot reproduce.
    """

    #: Human-readable identifier, used in logs and in the answer we return so
    #: that an answer can always be traced to what produced it.
    name: str

    def generate(
        self,
        *,
        system: str,
        user: str,
        json_schema: dict[str, Any] | None = None,
    ) -> LLMResponse:
        """Produce one completion.

        ``json_schema`` asks the provider to constrain the output to that
        schema. A provider that cannot do so must still return text; the caller
        parses and validates regardless, because a constraint honoured by the
        decoder is a convenience, never a guarantee.
        """
        ...
