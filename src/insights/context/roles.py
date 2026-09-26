"""Inferring what kind of thing a column is, from its measurements only.

A deliberate line runs through this module: roles are inferred from **statistics**
and never from column names.

The reason is that the language model already reads the names. Whatever a column
is called, the model can see what it is called. A name-matching heuristic here
would add a second, worse opinion about the same evidence - one that contradicts
the name whenever the file is not in English business vocabulary, and one that
has to be maintained forever. What the model *cannot* see is that a column has
38 distinct values across half a million rows, or that a quarter of it is empty.
That is what this module contributes.

The consequence, accepted on purpose: we do not claim to tell a price from a
count. Both are ``measure``. That distinction is a claim about meaning, and the
evidence for it is the name.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ..config import Settings
from ..models.profile import ColumnProfile, LogicalType
from .formatting import percent


class ColumnRole(str, Enum):
    """The structural part a column plays in a table.

    These describe shape, not business meaning. ``measure`` covers a price and a
    weight and a count alike.
    """

    #: A date or a timestamp. Anything about periods, growth or trends needs one.
    TEMPORAL = "temporal"
    #: Two states, usually 0/1 or true/false.
    FLAG = "flag"
    #: Very nearly one distinct value per row: names a row.
    IDENTIFIER = "identifier"
    #: Many distinct values, each repeated: names a group of rows.
    KEY = "key"
    #: Few distinct values, heavily repeated: something to group or filter by.
    CATEGORY = "category"
    #: Long text. Readable, not groupable.
    FREE_TEXT = "free_text"
    #: A number to aggregate.
    MEASURE = "measure"
    #: Empty, or a type we do not model.
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class RoleAssessment:
    """A role and the measurement that led to it.

    The evidence travels with the role so that a wrong guess can be explained
    rather than argued about.
    """

    role: ColumnRole
    evidence: str


def infer_role(column: ColumnProfile, *, settings: Settings) -> RoleAssessment:
    """Assign one role to one column. First rule that matches wins."""
    if column.null_rate >= 1.0:
        return RoleAssessment(ColumnRole.UNKNOWN, "every value is missing")

    if column.logical_type.is_temporal:
        return RoleAssessment(
            ColumnRole.TEMPORAL, f"stored as {column.logical_type.value}"
        )

    if column.logical_type is LogicalType.BOOLEAN:
        return RoleAssessment(ColumnRole.FLAG, "stored as boolean")

    if _is_zero_one_integer(column):
        return RoleAssessment(ColumnRole.FLAG, "only the values 0 and 1 appear")

    # Checked before the numeric rule: an integer key is an identifier, not a
    # quantity to be summed.
    #
    # The row count matters as much as the ratio. In a five-row file every
    # column of small integers has one distinct value per row, and calling that
    # an identifier is reading a coincidence as a fact.
    if (
        column.logical_type in (LogicalType.TEXT, LogicalType.INTEGER)
        and column.non_null_count >= settings.identifier_min_values
        and column.distinct_rate >= settings.identifier_distinct_rate
    ):
        return RoleAssessment(
            ColumnRole.IDENTIFIER,
            f"{percent(column.distinct_rate)} of the "
            f"{column.non_null_count:,} non-empty values are distinct",
        )

    if column.logical_type.is_numeric:
        return RoleAssessment(
            ColumnRole.MEASURE, f"a {column.logical_type.value} that repeats"
        )

    if column.logical_type is LogicalType.TEXT:
        if _is_long_text(column, settings):
            return RoleAssessment(
                ColumnRole.FREE_TEXT,
                f"values average {column.mean_length:.0f} characters",
            )
        if column.distinct_count <= settings.category_max_distinct:
            return RoleAssessment(
                ColumnRole.CATEGORY, f"only {column.distinct_count} distinct values"
            )
        return RoleAssessment(
            ColumnRole.KEY,
            f"{column.distinct_count:,} distinct short values, each repeated",
        )

    return RoleAssessment(
        ColumnRole.UNKNOWN, f"type {column.sql_type} is not one we model"
    )


def _is_zero_one_integer(column: ColumnProfile) -> bool:
    """True for an integer column that only ever holds 0 and 1.

    Tested on the measured minimum and maximum rather than on the name, so it
    catches a flag whatever it is called and never mistakes a year for one.
    """
    return (
        column.logical_type is LogicalType.INTEGER
        and column.distinct_count <= 2
        and isinstance(column.min_value, int)
        and isinstance(column.max_value, int)
        and column.min_value >= 0
        and column.max_value <= 1
    )


def _is_long_text(column: ColumnProfile, settings: Settings) -> bool:
    if column.mean_length is None:
        return False
    return (
        column.mean_length > settings.free_text_mean_length
        or (column.max_length or 0) > settings.free_text_max_length
    )

