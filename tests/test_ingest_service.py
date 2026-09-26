"""Tests for ingestion end to end, and for what is remembered afterwards."""

from __future__ import annotations

import pytest

from insights import registry
from insights.errors import DatasetNotFound, IngestionError
from insights.ingest import loader
from insights.ingest.service import ingest_csv
from insights.sql_identifiers import quote_ident

from .conftest import FIXTURES


def test_ingest_returns_a_complete_profile(con):
    profile = ingest_csv(FIXTURES / "rentals.csv", con=con)

    assert profile.row_count == 5
    assert profile.column_count == 8
    assert len(profile.columns) == 8
    assert profile.source_filename == "rentals.csv"
    assert profile.source_bytes > 0
    assert profile.table_name == f"ds_{profile.dataset_id}"


def test_profile_is_stored_and_reads_back_identically(con):
    profile = ingest_csv(FIXTURES / "rentals.csv", con=con)

    assert registry.get_profile(profile.dataset_id, con=con) == profile


def test_profile_survives_a_json_round_trip(con):
    """The profile crosses process boundaries as JSON: HTTP, storage, prompts."""
    profile = ingest_csv(FIXTURES / "rentals.csv", con=con)
    rebuilt = type(profile).model_validate_json(profile.model_dump_json())

    assert rebuilt == profile


def test_each_ingest_gets_its_own_dataset_and_table(con):
    first = ingest_csv(FIXTURES / "rentals.csv", con=con)
    second = ingest_csv(FIXTURES / "rentals.csv", con=con)

    assert first.dataset_id != second.dataset_id
    assert first.table_name != second.table_name
    assert {summary.dataset_id for summary in registry.list_datasets(con=con)} == {
        first.dataset_id,
        second.dataset_id,
    }


def test_listing_is_newest_first(con):
    first = ingest_csv(FIXTURES / "rentals.csv", con=con)
    second = ingest_csv(FIXTURES / "awkward_names.csv", con=con)

    listed = [summary.dataset_id for summary in registry.list_datasets(con=con)]
    assert listed.index(second.dataset_id) <= listed.index(first.dataset_id)


def test_unknown_dataset_is_a_domain_error(con):
    with pytest.raises(DatasetNotFound) as raised:
        registry.get_profile("does-not-exist", con=con)
    assert raised.value.http_status == 404


def test_a_failed_profile_leaves_no_table_behind(con, monkeypatch):
    """Half an ingest is worse than none: it would be listed and queried."""
    from insights.ingest import service

    monkeypatch.setattr(
        service, "profile_table", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    with pytest.raises(RuntimeError):
        ingest_csv(FIXTURES / "rentals.csv", con=con)

    tables = [row[0] for row in con.execute("SHOW TABLES").fetchall()]
    assert [name for name in tables if name.startswith("ds_")] == []
    assert registry.list_datasets(con=con) == []


def test_rejected_file_is_not_registered(con):
    with pytest.raises(IngestionError):
        ingest_csv(FIXTURES / "header_only.csv", con=con)
    assert registry.list_datasets(con=con) == []


def test_ingested_rows_are_queryable(con):
    profile = ingest_csv(FIXTURES / "rentals.csv", con=con)
    total = con.execute(
        f'SELECT sum("Days Hired") FROM {quote_ident(profile.table_name)}'
    ).fetchone()[0]

    assert total == 17
