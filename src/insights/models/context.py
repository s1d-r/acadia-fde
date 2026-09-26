"""The description of a dataset that the planner is given.

A :class:`SchemaContext` is a profile plus an interpretation of it. It is kept
separate from the profile for two reasons. The profile is measurement and will
not change; the interpretation is judgement and will. And the context carries
things the profile cannot: caveats about the file as a whole, and the fact that
some columns were left out because the file was too wide.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from ..context.roles import ColumnRole
from .profile import ColumnProfile


class ColumnContext(BaseModel):
    """One column, as the planner will be told about it."""

    profile: ColumnProfile
    role: ColumnRole
    role_evidence: str = Field(
        description="The measurement the role was inferred from, so a wrong "
        "guess can be explained."
    )

    @property
    def name(self) -> str:
        return self.profile.name


class SchemaContext(BaseModel):
    """Everything the planner is allowed to know about a dataset."""

    dataset_id: str
    table_name: str
    row_count: int
    column_count: int
    columns: list[ColumnContext]

    caveats: list[str] = Field(
        default_factory=list,
        description="Things true of the file as a whole that change what can "
        "honestly be answered: no header, untyped columns, no date column at "
        "all. These exist to make refusing easy and correct.",
    )

    omitted_column_count: int = Field(
        default=0,
        description="Columns left out because the file is wider than the "
        "prompt budget. Non-zero means the planner is not seeing everything.",
    )

    @property
    def column_names(self) -> list[str]:
        """Exactly the columns the planner may reference.

        The validator in slice 4 checks generated SQL against this list, so a
        column that is not here cannot appear in an answer.
        """
        return [column.name for column in self.columns]
