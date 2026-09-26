"""The profile of an ingested file.

This is the only description of a dataset the rest of the system is allowed to
use. It is built entirely from the file: names, types and statistics that were
measured, never assumed. Everything downstream - the schema context, the
planner prompt, the validator's list of legal columns - reads from here.

It is a Pydantic model because it is a contract that crosses boundaries: it is
stored as JSON, returned over HTTP, and rendered into a prompt.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field

from ..values import Scalar


class LogicalType(str, Enum):
    """DuckDB's storage types, collapsed into the handful of buckets that
    change how a column can be used in a query.

    ``BIGINT`` and ``SMALLINT`` differ to a database and not to us; a date and a
    number differ a great deal.
    """

    INTEGER = "integer"
    DECIMAL = "decimal"
    BOOLEAN = "boolean"
    DATE = "date"
    TIMESTAMP = "timestamp"
    TIME = "time"
    TEXT = "text"
    OTHER = "other"

    @property
    def is_numeric(self) -> bool:
        return self in (LogicalType.INTEGER, LogicalType.DECIMAL)

    @property
    def is_temporal(self) -> bool:
        return self in (LogicalType.DATE, LogicalType.TIMESTAMP, LogicalType.TIME)


class TypeInference(str, Enum):
    """How the column types were arrived at."""

    #: DuckDB read the whole file and inferred a type per column.
    AUTOMATIC = "automatic"
    #: Type inference failed, so every column was read as text. The dataset is
    #: still queryable, but downstream code must treat the types as unknown.
    ALL_TEXT_FALLBACK = "all_text_fallback"


class SampleValue(BaseModel):
    """One frequent value in a column, rendered as text for display."""

    value: str
    count: int


class ColumnProfile(BaseModel):
    """What was measured about one column."""

    name: str
    position: int = Field(description="Zero-based position in the file.")
    sql_type: str = Field(description="The type DuckDB gave the column, e.g. BIGINT.")
    logical_type: LogicalType

    non_null_count: int = Field(
        description="Rows where the column has a value. Small numbers here make "
        "every other statistic on this column weak evidence."
    )
    null_count: int
    null_rate: float = Field(ge=0.0, le=1.0)

    distinct_count: int
    distinct_rate: float = Field(
        ge=0.0,
        le=1.0,
        description="Distinct values over non-null values. 1.0 means every row "
        "differs, which is how identifiers look; a low value is how categories "
        "look.",
    )
    is_unique: bool = Field(
        description="No nulls and every row distinct: a candidate key."
    )

    min_value: Scalar = None
    max_value: Scalar = None
    mean_value: float | None = Field(
        default=None, description="Numeric columns only."
    )

    mean_length: float | None = Field(
        default=None,
        description="Text columns only: mean length in characters. Short values "
        "are codes and labels; long ones are prose.",
    )
    max_length: int | None = Field(
        default=None, description="Text columns only: longest value in characters."
    )

    sample_values: list[SampleValue] = Field(default_factory=list)


class TableProfile(BaseModel):
    """What was measured about one ingested file."""

    dataset_id: str
    table_name: str
    source_filename: str
    source_bytes: int
    row_count: int
    column_count: int
    ingested_at: datetime
    type_inference: TypeInference
    header_detected: bool = Field(
        default=True,
        description="False when the reader found no header row and named the "
        "columns itself. The names are then positional and mean nothing, which "
        "later slices must tell the user rather than guess around.",
    )
    columns: list[ColumnProfile]

    def column(self, name: str) -> ColumnProfile | None:
        """Look a column up by its exact name."""
        for column in self.columns:
            if column.name == name:
                return column
        return None


class DatasetSummary(BaseModel):
    """The one-line form used when listing datasets."""

    dataset_id: str
    source_filename: str
    row_count: int
    column_count: int
    ingested_at: datetime
