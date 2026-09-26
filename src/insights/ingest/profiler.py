"""Measure an ingested table.

The profiler answers, for every column: what type is it, how much of it is
missing, how many different values does it hold, what range does it cover, and
what do typical values look like. Those five things are what later slices use
to decide whether a question can be answered at all.

Deliberately, it draws no conclusions. It does not decide that a column is a
price or a date of sale. Naming roles is the schema context builder's job
(slice 2); keeping measurement and interpretation apart means the interpretation
can be changed without re-reading the data.
"""

from __future__ import annotations

import duckdb

from ..config import get_settings
from ..models.profile import ColumnProfile, LogicalType, SampleValue
from ..sql_identifiers import quote_ident
from ..values import to_jsonable

#: How many aggregates the wide query emits per column. Fixed so the result row
#: can be sliced by position.
_AGGREGATES_PER_COLUMN = 7

#: DuckDB type name -> our bucket. Matching is on the bare type name, so
#: DECIMAL(18,3) and TIMESTAMP WITH TIME ZONE land in the right place.
_TYPE_MAP: dict[str, LogicalType] = {
    "BOOLEAN": LogicalType.BOOLEAN,
    "TINYINT": LogicalType.INTEGER,
    "SMALLINT": LogicalType.INTEGER,
    "INTEGER": LogicalType.INTEGER,
    "BIGINT": LogicalType.INTEGER,
    "HUGEINT": LogicalType.INTEGER,
    "UTINYINT": LogicalType.INTEGER,
    "USMALLINT": LogicalType.INTEGER,
    "UINTEGER": LogicalType.INTEGER,
    "UBIGINT": LogicalType.INTEGER,
    "UHUGEINT": LogicalType.INTEGER,
    "FLOAT": LogicalType.DECIMAL,
    "REAL": LogicalType.DECIMAL,
    "DOUBLE": LogicalType.DECIMAL,
    "DECIMAL": LogicalType.DECIMAL,
    "NUMERIC": LogicalType.DECIMAL,
    "DATE": LogicalType.DATE,
    "TIMESTAMP": LogicalType.TIMESTAMP,
    "DATETIME": LogicalType.TIMESTAMP,
    "TIMESTAMPTZ": LogicalType.TIMESTAMP,
    "TIME": LogicalType.TIME,
    "TIMETZ": LogicalType.TIME,
    "VARCHAR": LogicalType.TEXT,
    "CHAR": LogicalType.TEXT,
    "TEXT": LogicalType.TEXT,
    "STRING": LogicalType.TEXT,
    "UUID": LogicalType.TEXT,
}


def classify_type(sql_type: str) -> LogicalType:
    """Map a DuckDB type string onto one of our buckets."""
    # Strip parameters and modifiers: "DECIMAL(18,3)" -> "DECIMAL",
    # "TIMESTAMP WITH TIME ZONE" -> "TIMESTAMP".
    base = sql_type.upper().split("(")[0].split(" WITH ")[0].strip()
    return _TYPE_MAP.get(base, LogicalType.OTHER)


def profile_table(
    table_name: str,
    *,
    con: duckdb.DuckDBPyConnection,
    row_count: int,
) -> list[ColumnProfile]:
    """Profile every column of ``table_name``."""
    settings = get_settings()
    quoted_table = quote_ident(table_name)
    described = con.execute(f"DESCRIBE {quoted_table}").fetchall()
    columns = [(str(row[0]), str(row[1])) for row in described]

    stats = _column_statistics(quoted_table, columns, con=con)

    profiles: list[ColumnProfile] = []
    for position, (name, sql_type) in enumerate(columns):
        logical_type = classify_type(sql_type)
        (
            non_null,
            distinct,
            minimum,
            maximum,
            mean,
            mean_length,
            max_length,
        ) = stats[position]
        null_count = row_count - non_null

        profiles.append(
            ColumnProfile(
                name=name,
                position=position,
                sql_type=sql_type,
                logical_type=logical_type,
                non_null_count=non_null,
                null_count=null_count,
                null_rate=_ratio(null_count, row_count),
                distinct_count=distinct,
                distinct_rate=_ratio(distinct, non_null),
                is_unique=row_count > 0 and null_count == 0 and distinct == row_count,
                min_value=to_jsonable(minimum),
                max_value=to_jsonable(maximum),
                mean_value=float(mean) if mean is not None else None,
                mean_length=float(mean_length) if mean_length is not None else None,
                max_length=int(max_length) if max_length is not None else None,
                sample_values=_frequent_values(
                    quoted_table,
                    name,
                    con=con,
                    limit=settings.sample_values_per_column,
                    max_chars=settings.sample_value_max_chars,
                ),
            )
        )
    return profiles


def _column_statistics(
    quoted_table: str,
    columns: list[tuple[str, str]],
    *,
    con: duckdb.DuckDBPyConnection,
) -> list[tuple]:
    """Compute per-column aggregates in one pass over the table.

    One query with ``7 * n`` aggregates rather than ``n`` queries: the table is
    scanned once instead of once per column, which is the difference between a
    profile that takes a moment and one that takes a minute on a large file.
    """
    selects: list[str] = []
    for name, sql_type in columns:
        column = quote_ident(name)
        logical_type = classify_type(sql_type)
        selects.append(f"count({column})")
        selects.append(f"count(DISTINCT {column})")
        if logical_type.is_numeric or logical_type.is_temporal or logical_type is LogicalType.BOOLEAN:
            # min/max mean something for ordered types. On free text they would
            # only report alphabetical extremes, which tell nobody anything.
            selects.append(f"min({column})")
            selects.append(f"max({column})")
        else:
            selects.append("NULL")
            selects.append("NULL")
        selects.append(f"avg({column})" if logical_type.is_numeric else "NULL")
        if logical_type is LogicalType.TEXT:
            # How long the values are is what separates a short code from a
            # sentence, when both have thousands of distinct values.
            selects.append(f"avg(length({column}))")
            selects.append(f"max(length({column}))")
        else:
            selects.append("NULL")
            selects.append("NULL")

    row = con.execute(f"SELECT {', '.join(selects)} FROM {quoted_table}").fetchone()
    return [
        tuple(row[i * _AGGREGATES_PER_COLUMN : (i + 1) * _AGGREGATES_PER_COLUMN])
        for i in range(len(columns))
    ]


def _frequent_values(
    quoted_table: str,
    column_name: str,
    *,
    con: duckdb.DuckDBPyConnection,
    limit: int,
    max_chars: int,
) -> list[SampleValue]:
    """The most common non-null values in a column, as text.

    Frequency order rather than the first rows found: the common values are the
    ones that show the shape of a category column, and the ordering is stable
    across runs, which matters because these end up in a prompt.
    """
    column = quote_ident(column_name)
    try:
        rows = con.execute(
            f"SELECT CAST({column} AS VARCHAR) AS value, count(*) AS frequency "
            f"FROM {quoted_table} WHERE {column} IS NOT NULL "
            f"GROUP BY value ORDER BY frequency DESC, value ASC LIMIT {int(limit)}"
        ).fetchall()
    except duckdb.Error:
        # Some column types (nested types, blobs) have no text form. A column we
        # cannot sample is still a column worth reporting.
        return []

    return [
        SampleValue(value=_truncate(str(value), max_chars), count=int(frequency))
        for value, frequency in rows
    ]


def _ratio(part: int, whole: int) -> float:
    """Guard against dividing by zero on an all-null column."""
    return part / whole if whole else 0.0


def _truncate(text: str, max_chars: int) -> str:
    return text if len(text) <= max_chars else text[: max_chars - 1] + "…"

