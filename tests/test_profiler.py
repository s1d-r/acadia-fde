"""Tests for what we measure about a table.

The fixture is a car rental file: different column names, different types and a
different shape from the development dataset, because the profiler is the piece
that has to work on a file nobody anticipated.
"""

from __future__ import annotations

import pytest

from insights.ingest import loader
from insights.ingest.profiler import classify_type, profile_table
from insights.models.profile import LogicalType
from insights.sql_identifiers import new_dataset_id

from .conftest import FIXTURES


@pytest.fixture
def rentals(con):
    result = loader.load_csv(FIXTURES / "rentals.csv", dataset_id=new_dataset_id(), con=con)
    columns = profile_table(result.table_name, con=con, row_count=result.row_count)
    return {column.name: column for column in columns}


def test_every_column_is_profiled_in_file_order(rentals):
    assert [column.position for column in rentals.values()] == list(range(8))
    assert list(rentals) == [
        "Booking Ref",
        "Picked Up",
        "Vehicle, Class",
        "Days Hired",
        "Daily Rate",
        "Member ID",
        "Branch",
        "Notes",
    ]


def test_types_are_bucketed(rentals):
    assert rentals["Booking Ref"].logical_type is LogicalType.TEXT
    assert rentals["Picked Up"].logical_type is LogicalType.DATE
    assert rentals["Days Hired"].logical_type is LogicalType.INTEGER
    assert rentals["Daily Rate"].logical_type is LogicalType.DECIMAL


def test_an_identifier_looking_column_is_reported_as_unique(rentals):
    booking = rentals["Booking Ref"]
    assert booking.is_unique is True
    assert booking.distinct_rate == 1.0


def test_a_category_looking_column_is_reported_as_repeating(rentals):
    branch = rentals["Branch"]
    assert branch.distinct_count == 2
    assert branch.distinct_rate == pytest.approx(0.4)
    assert branch.is_unique is False


def test_missing_values_are_counted(rentals):
    assert rentals["Member ID"].null_count == 1
    assert rentals["Member ID"].null_rate == pytest.approx(0.2)
    assert rentals["Notes"].null_count == 4
    assert rentals["Notes"].null_rate == pytest.approx(0.8)


def test_ranges_are_measured_for_ordered_columns(rentals):
    assert rentals["Picked Up"].min_value == "2023-04-01"
    assert rentals["Picked Up"].max_value == "2023-05-12"
    assert rentals["Days Hired"].min_value == 1
    assert rentals["Days Hired"].max_value == 7
    assert rentals["Daily Rate"].mean_value == pytest.approx(52.35)


def test_ranges_are_not_invented_for_free_text(rentals):
    """Alphabetical extremes of a text column describe nothing."""
    assert rentals["Notes"].min_value is None
    assert rentals["Notes"].max_value is None
    assert rentals["Booking Ref"].mean_value is None


def test_sample_values_are_the_most_frequent_ones(rentals):
    samples = rentals["Vehicle, Class"].sample_values
    assert samples[0].value == "Hatchback, Small"
    assert samples[0].count == 2
    # Nulls are never offered as examples of what a column holds.
    assert [sample.value for sample in rentals["Notes"].sample_values] == ["upgraded"]


def test_sample_values_are_truncated(con, monkeypatch, tmp_path):
    monkeypatch.setenv("INSIGHTS_SAMPLE_VALUE_MAX_CHARS", "10")
    from insights.config import get_settings

    get_settings.cache_clear()
    source = tmp_path / "long.csv"
    source.write_text("note\n" + "x" * 500 + "\n", encoding="utf-8")

    result = loader.load_csv(source, dataset_id=new_dataset_id(), con=con)
    columns = profile_table(result.table_name, con=con, row_count=result.row_count)

    assert len(columns[0].sample_values[0].value) == 10


def test_an_all_null_column_does_not_divide_by_zero(con, tmp_path):
    source = tmp_path / "blank.csv"
    source.write_text("filled,blank\n1,\n2,\n", encoding="utf-8")

    result = loader.load_csv(source, dataset_id=new_dataset_id(), con=con)
    blank = profile_table(result.table_name, con=con, row_count=result.row_count)[1]

    assert blank.null_rate == 1.0
    assert blank.distinct_count == 0
    assert blank.distinct_rate == 0.0
    assert blank.sample_values == []


@pytest.mark.parametrize(
    ("sql_type", "expected"),
    [
        ("BIGINT", LogicalType.INTEGER),
        ("DECIMAL(18,3)", LogicalType.DECIMAL),
        ("TIMESTAMP WITH TIME ZONE", LogicalType.TIMESTAMP),
        ("VARCHAR", LogicalType.TEXT),
        ("BOOLEAN", LogicalType.BOOLEAN),
        ("STRUCT(a INTEGER)", LogicalType.OTHER),
    ],
)
def test_type_bucketing(sql_type, expected):
    assert classify_type(sql_type) is expected
