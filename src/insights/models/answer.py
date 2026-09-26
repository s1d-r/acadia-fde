"""What a caller gets back from asking a question.

An answer always carries the SQL that produced it and the model that wrote that
SQL. That is not a debugging nicety: the promise of this system is a figure you
can trust, and a figure you cannot check is not one you can trust. The query is
part of the answer.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from ..values import Scalar
from .plan import PlanOutcome


class QueryResult(BaseModel):
    """Rows from one executed query."""

    columns: list[str] = Field(description="Result column names, in order.")
    rows: list[list[Scalar]]
    row_count: int = Field(description="Rows returned, after any truncation.")
    truncated: bool = Field(
        default=False,
        description="True when the query matched more rows than we return. The "
        "caller is told rather than silently shown a prefix.",
    )
    duration_ms: int


class Answer(BaseModel):
    """A question, and what became of it."""

    dataset_id: str
    question: str
    outcome: PlanOutcome

    sql: str | None = Field(
        default=None, description="The query that was run. None for a refusal."
    )
    reason: str = Field(
        description="What the query computes, or what is missing from the data."
    )
    result: QueryResult | None = Field(
        default=None, description="Rows. None for a refusal."
    )

    model: str
    planning_ms: int

    @property
    def is_refusal(self) -> bool:
        return self.outcome is PlanOutcome.REFUSAL
