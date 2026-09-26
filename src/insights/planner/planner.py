"""Question plus schema context in; SQL or a refusal out.

The planner owns exactly one thing: getting a decision out of a model and
turning it into a value the rest of the system can rely on. It does not run
anything, does not check whether the SQL is safe, and does not decide whether
the SQL is correct. Those belong to the validator and the executor, and keeping
them out of here is what makes it possible to test each of them alone.
"""

from __future__ import annotations

import json

from ..errors import PlanningFailed
from ..llm.base import LLMClient
from ..models.context import SchemaContext
from ..models.plan import PlanOutcome, QueryPlan
from .prompts import PLAN_JSON_SCHEMA, SYSTEM_PROMPT, build_user_prompt

#: A refusal with no reason is useless to the person who asked, so we supply one
#: rather than showing an empty string.
_UNEXPLAINED_REFUSAL = "The question cannot be answered from the columns in this file."


def plan_query(
    question: str,
    context: SchemaContext,
    *,
    client: LLMClient,
) -> QueryPlan:
    """Ask the model what to do with ``question``.

    Raises :class:`PlanningFailed` only when the model returns something that is
    not a decision at all. A refusal is a decision, and comes back as a plan.
    """
    if not question.strip():
        raise PlanningFailed("The question is empty")

    response = client.generate(
        system=SYSTEM_PROMPT,
        user=build_user_prompt(question, context),
        json_schema=PLAN_JSON_SCHEMA,
    )

    decision = _parse(response.text)
    answerable = bool(decision.get("answerable"))
    sql = str(decision.get("sql") or "").strip()
    reason = str(decision.get("reason") or "").strip()

    # A model that says "yes" and then produces no query has not answered. Treat
    # that as a refusal rather than passing an empty string to the executor:
    # the honest report is that we have no query, not that the query is blank.
    if answerable and not sql:
        return QueryPlan(
            outcome=PlanOutcome.REFUSAL,
            reason=reason or _UNEXPLAINED_REFUSAL,
            model=response.model,
            duration_ms=response.duration_ms,
        )

    if not answerable:
        return QueryPlan(
            outcome=PlanOutcome.REFUSAL,
            reason=reason or _UNEXPLAINED_REFUSAL,
            model=response.model,
            duration_ms=response.duration_ms,
        )

    return QueryPlan(
        outcome=PlanOutcome.QUERY,
        sql=sql,
        reason=reason or "Runs the generated query.",
        model=response.model,
        duration_ms=response.duration_ms,
    )


def _parse(text: str) -> dict:
    """Read the model's JSON, tolerating the two things models do to it.

    The decoder is constrained to our schema, so in the normal case this is a
    plain ``json.loads``. It is not trusted to be: a provider swap, a server
    that ignores the constraint, or a model that wraps its answer in a code
    fence would all arrive here, and a stack trace from ``json.loads`` is not an
    error message anyone can act on.
    """
    candidate = text.strip()

    if candidate.startswith("```"):
        # ```json\n{...}\n```
        fenced = candidate.split("```")
        candidate = next(
            (
                part.removeprefix("json").strip()
                for part in fenced
                if part.strip().removeprefix("json").strip().startswith("{")
            ),
            candidate,
        )

    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise PlanningFailed(
            "The model did not return a usable decision",
            details={"received": _excerpt(text)},
        ) from exc

    if not isinstance(parsed, dict):
        raise PlanningFailed(
            "The model returned JSON, but not an object",
            details={"received": _excerpt(text)},
        )
    if "answerable" not in parsed:
        raise PlanningFailed(
            "The model did not say whether the question was answerable",
            details={"received": _excerpt(text)},
        )
    return parsed


def _excerpt(text: str, limit: int = 200) -> str:
    """Enough of a bad response to debug with, not enough to fill a log."""
    collapsed = " ".join(text.split())
    return collapsed if len(collapsed) <= limit else collapsed[: limit - 1] + "…"
