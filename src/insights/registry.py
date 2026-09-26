"""Where profiles are kept.

Ingesting a file produces two things: a table of rows, and a record describing
it. The rows live in DuckDB; so does the record, in a separate ``meta`` schema
so our bookkeeping can never collide with a user's data.

The profile is stored as a JSON document rather than as columns. The profile
model will grow - roles, ranges, whatever a later slice needs - and a JSON
column absorbs that without a migration. Nothing queries inside it; it is always
read whole, by id.
"""

from __future__ import annotations

from datetime import datetime, timezone

import duckdb

from .errors import DatasetNotFound
from .models.profile import DatasetSummary, TableProfile

_META_SCHEMA = "meta"
_DATASETS_TABLE = "meta.datasets"


def ensure_schema(con: duckdb.DuckDBPyConnection) -> None:
    """Create the bookkeeping tables if they are not there yet.

    Called on every write rather than once at startup, so a fresh database file
    needs no separate migration step.
    """
    con.execute(f"CREATE SCHEMA IF NOT EXISTS {_META_SCHEMA}")
    con.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_DATASETS_TABLE} (
            dataset_id      VARCHAR PRIMARY KEY,
            table_name      VARCHAR NOT NULL,
            source_filename VARCHAR NOT NULL,
            row_count       BIGINT  NOT NULL,
            column_count    INTEGER NOT NULL,
            ingested_at     TIMESTAMP NOT NULL,  -- always UTC, see _to_utc
            profile_json    VARCHAR NOT NULL
        )
        """
    )


def save_profile(profile: TableProfile, *, con: duckdb.DuckDBPyConnection) -> None:
    """Insert or replace the record for a dataset."""
    ensure_schema(con)
    con.execute(
        f"""
        INSERT OR REPLACE INTO {_DATASETS_TABLE}
            (dataset_id, table_name, source_filename, row_count, column_count,
             ingested_at, profile_json)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [
            profile.dataset_id,
            profile.table_name,
            profile.source_filename,
            profile.row_count,
            profile.column_count,
            _naive_utc(profile.ingested_at),
            profile.model_dump_json(),
        ],
    )


def get_profile(dataset_id: str, *, con: duckdb.DuckDBPyConnection) -> TableProfile:
    """Load one profile, or raise :class:`DatasetNotFound`."""
    ensure_schema(con)
    row = con.execute(
        f"SELECT profile_json FROM {_DATASETS_TABLE} WHERE dataset_id = ?",
        [dataset_id],
    ).fetchone()
    if row is None:
        raise DatasetNotFound(
            "No dataset with that id has been ingested",
            details={"dataset_id": dataset_id},
        )
    return TableProfile.model_validate_json(row[0])


def list_datasets(*, con: duckdb.DuckDBPyConnection) -> list[DatasetSummary]:
    """Every dataset, newest first."""
    ensure_schema(con)
    rows = con.execute(
        f"""
        SELECT dataset_id, source_filename, row_count, column_count, ingested_at
        FROM {_DATASETS_TABLE}
        ORDER BY ingested_at DESC
        """
    ).fetchall()
    return [
        DatasetSummary(
            dataset_id=dataset_id,
            source_filename=source_filename,
            row_count=row_count,
            column_count=column_count,
            ingested_at=_as_utc(ingested_at),
        )
        for dataset_id, source_filename, row_count, column_count, ingested_at in rows
    ]


def _naive_utc(moment: datetime) -> datetime:
    """Store timestamps as UTC without an offset.

    DuckDB can hold an offset, but reading one back needs an extra dependency
    for no benefit here: every timestamp we write is already UTC. Dropping the
    offset on the way in and restoring it on the way out keeps the stored values
    directly comparable and the Python side timezone-aware throughout.
    """
    return moment.astimezone(timezone.utc).replace(tzinfo=None)


def _as_utc(moment: datetime) -> datetime:
    """The inverse of :func:`_naive_utc`."""
    return moment.replace(tzinfo=timezone.utc)
