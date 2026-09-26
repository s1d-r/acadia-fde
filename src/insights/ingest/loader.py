"""Load a CSV file into a DuckDB table.

This module knows nothing about what the data means. Its whole job is: given a
path, end up with a table full of rows and an honest account of how the types
were decided.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import duckdb

from ..config import get_settings
from ..errors import IngestionError, InvalidFile
from ..models.profile import TypeInference
from ..sql_identifiers import quote_ident, table_name_for

#: How we try to read a file, in order. Kept as a constant so the retry
#: behaviour can be exercised directly by a test.
LOAD_ATTEMPTS: list[tuple[str, TypeInference]] = [
    ("auto_detect = true, sample_size = -1", TypeInference.AUTOMATIC),
    ("auto_detect = true, all_varchar = true", TypeInference.ALL_TEXT_FALLBACK),
]

#: The names DuckDB invents when it decides a file has no header row.
_GENERATED_COLUMN_NAME = re.compile(r"^column\d+$")


@dataclass(frozen=True)
class LoadResult:
    table_name: str
    row_count: int
    column_count: int
    type_inference: TypeInference
    header_detected: bool


def validate_source(path: Path) -> int:
    """Check the file before handing it to the database. Returns its size.

    Fails at the boundary with a specific message, so the caller never sees a
    database error for something we could have said plainly.
    """
    if not path.exists() or not path.is_file():
        raise InvalidFile(f"No readable file at {path.name}", details={"path": path.name})

    size = path.stat().st_size
    if size == 0:
        raise InvalidFile("The file is empty", details={"path": path.name})

    limit = get_settings().max_csv_bytes
    if size > limit:
        raise InvalidFile(
            "The file is larger than this service accepts",
            details={"size_bytes": size, "limit_bytes": limit},
        )
    return size


def load_csv(
    path: Path,
    *,
    dataset_id: str,
    con: duckdb.DuckDBPyConnection,
) -> LoadResult:
    """Read ``path`` into a new table and return what landed there.

    Two attempts, in order:

    1. Let DuckDB infer a type per column, reading the *whole* file to decide
       (``sample_size=-1``). Sampling the first few thousand rows is faster but
       guesses wrong on a column that only turns messy late in the file, and a
       wrong type is worse than a slow load.
    2. If that fails, read every column as text. The dataset stays queryable and
       the result records that the types are not to be trusted.
    """
    validate_source(path)
    table = table_name_for(dataset_id)
    quoted = quote_ident(table)

    last_error: Exception | None = None
    for options, inference in LOAD_ATTEMPTS:
        try:
            # The path is a bound parameter, never interpolated into the SQL.
            con.execute(
                f"CREATE OR REPLACE TABLE {quoted} AS "
                f"SELECT * FROM read_csv(?, {options})",
                [str(path)],
            )
            break
        except duckdb.Error as exc:
            last_error = exc
    else:
        raise IngestionError(
            "The file could not be read as CSV",
            details={"reason": _first_line(last_error)},
        )

    try:
        row_count = con.execute(f"SELECT count(*) FROM {quoted}").fetchone()[0]
        column_names = [str(row[0]) for row in con.execute(f"DESCRIBE {quoted}").fetchall()]
    except duckdb.Error as exc:  # pragma: no cover - the table exists by here
        drop_table(table, con=con)
        raise IngestionError(
            "The file was read but the resulting table could not be inspected",
            details={"reason": _first_line(exc)},
        ) from exc

    column_count = len(column_names)
    if column_count == 0:
        drop_table(table, con=con)
        raise IngestionError("The file has no columns", details={"path": path.name})

    if row_count == 0:
        # A header with nothing under it. Better to reject now than to accept a
        # dataset every future question would have to refuse.
        drop_table(table, con=con)
        raise IngestionError(
            "The file has a header but no data rows", details={"path": path.name}
        )

    return LoadResult(
        table_name=table,
        row_count=row_count,
        column_count=column_count,
        type_inference=inference,
        header_detected=not all(
            _GENERATED_COLUMN_NAME.match(name) for name in column_names
        ),
    )


def drop_table(table_name: str, *, con: duckdb.DuckDBPyConnection) -> None:
    """Remove a table. Used to clean up after a failed ingest."""
    con.execute(f"DROP TABLE IF EXISTS {quote_ident(table_name)}")


def _first_line(error: Exception | None) -> str:
    """The first line of a database error.

    Database errors can run to many lines of context. One line is enough for a
    caller to know what to fix, and keeps the rest out of an API response.
    """
    if error is None:
        return "unknown error"
    return str(error).strip().splitlines()[0]
