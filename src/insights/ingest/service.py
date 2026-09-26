"""Ingestion, end to end.

One function that the CLI today, and the job layer later, both call: take a file
off the disk, put its rows in a table, measure it, remember it.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import duckdb

from .. import db, registry
from ..errors import IngestionError
from ..models.profile import TableProfile
from ..sql_identifiers import new_dataset_id
from .loader import drop_table, load_csv, validate_source
from .profiler import profile_table


def ingest_csv(
    path: Path,
    *,
    original_filename: str | None = None,
    con: duckdb.DuckDBPyConnection | None = None,
) -> TableProfile:
    """Ingest one CSV and return its profile.

    On any failure after the table exists, the table is dropped. A half-ingested
    dataset is worse than none: it would be listed, queried, and would answer
    with rows nobody had checked.
    """
    connection = con if con is not None else db.session()
    size = validate_source(path)
    dataset_id = new_dataset_id()

    loaded = load_csv(path, dataset_id=dataset_id, con=connection)

    try:
        columns = profile_table(
            loaded.table_name, con=connection, row_count=loaded.row_count
        )
        profile = TableProfile(
            dataset_id=dataset_id,
            table_name=loaded.table_name,
            source_filename=original_filename or path.name,
            source_bytes=size,
            row_count=loaded.row_count,
            column_count=loaded.column_count,
            ingested_at=datetime.now(timezone.utc),
            type_inference=loaded.type_inference,
            header_detected=loaded.header_detected,
            columns=columns,
        )
        registry.save_profile(profile, con=connection)
    except duckdb.Error as exc:
        drop_table(loaded.table_name, con=connection)
        raise IngestionError(
            "The file was loaded but could not be profiled",
            details={"reason": str(exc).strip().splitlines()[0]},
        ) from exc
    except Exception:
        drop_table(loaded.table_name, con=connection)
        raise

    return profile
