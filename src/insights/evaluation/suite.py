"""Evaluation suites: questions with known right answers.

The interesting decision here is how a right answer is written down.

The obvious way is to record the number. "Top product is REGENCY CAKESTAND,
158569.32." That breaks the moment the CSV changes, it cannot be reused on a
second file, and it silently rots: nobody notices the expected number was
copied from a run that was itself wrong.

Instead, each case carries **truth SQL**: a query written by hand that defines
what the right answer is. The harness runs it and compares the model's result to
it. The expected answer is therefore derived from the data every time, the same
suite works on any file with the same shape, and reviewing a case means reading
a query rather than trusting a number.

Unanswerable cases carry no SQL. Their expected outcome is a refusal.
"""

from __future__ import annotations

import json
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field, model_validator


class Expectation(str, Enum):
    """What a case expects to happen."""

    #: The answer must match the truth query's single value.
    SCALAR = "scalar"
    #: The answer's first column must match the truth query's, in order.
    RANKING = "ranking"
    #: The system must refuse, because the data cannot answer it.
    REFUSAL = "refusal"


class Case(BaseModel):
    """One question with a known right answer."""

    id: str
    question: str
    expect: Expectation

    truth_sql: str | None = Field(
        default=None,
        description="The query that defines the right answer. Required unless "
        "the case expects a refusal.",
    )
    why: str = Field(
        default="",
        description="Why this case is here. Read by whoever has to judge a "
        "failure, which is the moment the intent matters most.",
    )
    tolerance: float = Field(
        default=0.01,
        description="Relative tolerance for a scalar. Floating point sums over "
        "hundreds of thousands of rows do not land on the same last digit.",
    )

    @model_validator(mode="after")
    def _truth_sql_matches_expectation(self) -> "Case":
        if self.expect is Expectation.REFUSAL:
            if self.truth_sql:
                raise ValueError(
                    f"case {self.id!r} expects a refusal but carries truth SQL"
                )
        elif not self.truth_sql:
            raise ValueError(f"case {self.id!r} needs truth SQL to be checked against")
        return self


class Suite(BaseModel):
    """A set of cases against one CSV."""

    name: str
    csv: str = Field(description="Path to the CSV, relative to the repository root.")
    description: str = ""
    cases: list[Case]

    @model_validator(mode="after")
    def _ids_are_unique(self) -> "Suite":
        seen = [case.id for case in self.cases]
        duplicates = {name for name in seen if seen.count(name) > 1}
        if duplicates:
            raise ValueError(f"duplicate case ids: {sorted(duplicates)}")
        return self

    @property
    def refusal_cases(self) -> list[Case]:
        return [c for c in self.cases if c.expect is Expectation.REFUSAL]


def load_suite(path: Path) -> Suite:
    """Read a suite from disk."""
    return Suite.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))


def suite_paths(directory: Path) -> list[Path]:
    return sorted(Path(directory).glob("*.json"))
