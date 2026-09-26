"""What the planner produces.

A plan is one of two things: a query to run, or a refusal with a reason. Both
are successful outcomes. A refusal is not an error, does not raise, and is not
an empty result - it is the correct answer to a question the data cannot
support, and it is carried through the system as a first-class value all the way
to the caller.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class PlanOutcome(str, Enum):
    QUERY = "query"
    REFUSAL = "refusal"


class QueryPlan(BaseModel):
    """The planner's decision about one question."""

    outcome: PlanOutcome

    sql: str | None = Field(
        default=None, description="The query to run. Present only for a query outcome."
    )

    reason: str = Field(
        description="For a query: one sentence on what it computes, shown to "
        "the user beside the result. For a refusal: what is missing from the "
        "data, named specifically."
    )

    model: str = Field(description="Which model decided this, so an answer can be traced.")
    duration_ms: int

    @property
    def is_refusal(self) -> bool:
        return self.outcome is PlanOutcome.REFUSAL
