"""Tests for turning a file into a table.

These cover the cases that would silently corrupt every later answer: a name we
failed to quote, a file we should have rejected, a header that was not there.
"""

from __future__ import annotations

import pytest

from insights.errors import IngestionError, InvalidFile
from insights.ingest import loader
from insights.models.profile import TypeInference
from insights.sql_identifiers import new_dataset_id, quote_ident

from .conftest import FIXTURES


def test_loads_rows_and_columns(con):
    result = loader.load_csv(FIXTURES / "rentals.csv", dataset_id=new_dataset_id(), con=con)

    assert result.row_count == 5
    assert result.column_count == 8
    assert result.type_inference is TypeInference.AUTOMATIC
    assert result.header_detected is True


def test_column_names_survive_quoting_and_unicode(con):
    """Names that would break a naive query must round-trip untouched."""
    result = loader.load_csv(
        FIXTURES / "awkward_names.csv", dataset_id=new_dataset_id(), con=con
    )
    names = [
        row[0]
        for row in con.execute(f"DESCRIBE {quote_ident(result.table_name)}").fetchall()
    ]

    assert names == ['id"x', "select", "café", "drop table t; --", "Ünïcödé Column"]
    # The name containing SQL was stored as a name, not executed as SQL.
    assert con.execute(f"SELECT count(*) FROM {quote_ident(result.table_name)}").fetchone()[0] == 2


def test_rejects_empty_file(con):
    with pytest.raises(InvalidFile) as raised:
        loader.load_csv(FIXTURES / "empty.csv", dataset_id=new_dataset_id(), con=con)
    assert raised.value.code == "invalid_file"


def test_rejects_missing_file(con, tmp_path):
    with pytest.raises(InvalidFile):
        loader.load_csv(tmp_path / "nope.csv", dataset_id=new_dataset_id(), con=con)


def test_rejects_file_over_the_size_limit(con, monkeypatch):
    monkeypatch.setenv("INSIGHTS_MAX_CSV_BYTES", "10")
    from insights.config import get_settings

    get_settings.cache_clear()
    with pytest.raises(InvalidFile) as raised:
        loader.load_csv(FIXTURES / "rentals.csv", dataset_id=new_dataset_id(), con=con)
    assert raised.value.details["limit_bytes"] == 10


def test_rejects_header_with_no_rows(con):
    """A dataset with no rows could only ever produce empty answers."""
    with pytest.raises(IngestionError) as raised:
        loader.load_csv(FIXTURES / "header_only.csv", dataset_id=new_dataset_id(), con=con)
    assert raised.value.code == "ingestion_failed"


def test_reports_when_no_header_was_found(con):
    """A ragged file makes the reader give up on the header and invent names.

    It loads, but the names carry no meaning, and the profile has to say so
    rather than let a later slice read meaning into "column0".
    """
    result = loader.load_csv(FIXTURES / "ragged.csv", dataset_id=new_dataset_id(), con=con)
    assert result.header_detected is False


def test_falls_back_to_reading_everything_as_text(con, monkeypatch):
    """If type inference fails, the file is still loaded, and says so."""
    monkeypatch.setattr(
        loader,
        "LOAD_ATTEMPTS",
        [
            ("no_such_option = true", TypeInference.AUTOMATIC),
            ("auto_detect = true, all_varchar = true", TypeInference.ALL_TEXT_FALLBACK),
        ],
    )
    result = loader.load_csv(FIXTURES / "rentals.csv", dataset_id=new_dataset_id(), con=con)

    assert result.type_inference is TypeInference.ALL_TEXT_FALLBACK
    types = {
        row[1]
        for row in con.execute(f"DESCRIBE {quote_ident(result.table_name)}").fetchall()
    }
    assert types == {"VARCHAR"}


def test_unreadable_file_raises_a_domain_error_not_a_database_error(con, monkeypatch):
    monkeypatch.setattr(
        loader, "LOAD_ATTEMPTS", [("no_such_option = true", TypeInference.AUTOMATIC)]
    )
    with pytest.raises(IngestionError) as raised:
        loader.load_csv(FIXTURES / "rentals.csv", dataset_id=new_dataset_id(), con=con)

    assert raised.value.code == "ingestion_failed"
    assert "\n" not in raised.value.details["reason"]
