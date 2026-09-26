"""Tests for running a validated query under limits.

The executor no longer decides what is safe - that moved to the validator in
slice 4. What is tested here is the two limits it does own: how many rows come
back, and what happens to a query that will not finish.
"""

from __future__ import annotations

import time
from typing import get_type_hints

import pytest

from insights.context import build_context
from insights.errors import QueryFailed, QueryTimeout
from insights.executor import run_query
from insights.ingest.service import ingest_csv
from insights.validator import ValidatedQuery, validate_sql

from .conftest import FIXTURES


@pytest.fixture
def loans(con):
    return build_context(ingest_csv(FIXTURES / "library_loans.csv", con=con))


@pytest.fixture
def query(con, loans):
    def build(sql: str) -> ValidatedQuery:
        return validate_sql(sql, context=loans, con=con)

    return build


@pytest.fixture
def table(loans):
    return f'"{loans.table_name}"'


# --- the guarantee that unchecked SQL cannot get here -----------------------


def test_the_executor_accepts_only_validated_queries():
    """The type is the guarantee.

    ``run_query`` takes a ValidatedQuery, which only the validator produces, so
    a future caller cannot skip validation by passing a string. This test exists
    so that loosening the signature has to be a deliberate act.
    """
    assert get_type_hints(run_query)["query"] is ValidatedQuery


# --- results ----------------------------------------------------------------


def test_rows_come_back_with_their_column_names(con, query, table):
    result = run_query(
        query(f'SELECT "Branch Library", count(*) AS n FROM {table} GROUP BY 1 ORDER BY 1'),
        con=con,
    )

    assert result.columns == ["Branch Library", "n"]
    assert result.row_count == 4
    assert result.rows[0] == ["Central", 75]
    assert result.truncated is False


def test_values_are_converted_to_something_json_can_hold(con, query, table):
    """A date out of the database is a Python date, which JSON cannot encode."""
    result = run_query(query(f'SELECT min("Borrowed On") AS d FROM {table}'), con=con)
    assert result.rows == [["2022-01-04"]]


def test_more_rows_than_allowed_are_truncated_and_the_caller_is_told(con, query, table):
    result = run_query(query(f"SELECT * FROM {table}"), con=con, max_rows=5)

    assert result.row_count == 5
    assert result.truncated is True


def test_exactly_the_limit_is_not_reported_as_truncated(con, query, table):
    result = run_query(query(f"SELECT * FROM {table} LIMIT 5"), con=con, max_rows=5)

    assert result.row_count == 5
    assert result.truncated is False


def test_an_empty_result_is_a_result_not_a_failure(con, query, table):
    result = run_query(query(f'SELECT * FROM {table} WHERE "Days Kept" > 10000'), con=con)

    assert result.row_count == 0
    assert result.rows == []
    assert result.columns


# --- limits -----------------------------------------------------------------


@pytest.fixture
def endless(query, table):
    """A query that passes validation and will not finish in a hurry.

    Four-way self join over 300 rows is 8.1 billion combinations, and the hash
    filter stops the optimiser reducing it to a count it already knows.
    """
    return query(
        f"SELECT count(*) FROM {table} a, {table} b, {table} c, {table} d "
        'WHERE hash(a."Days Kept" * b."Days Kept" + c."Days Kept" + d."Days Kept") % 7 = 0'
    )


def test_a_query_that_runs_too_long_is_cancelled(con, endless):
    started = time.perf_counter()
    with pytest.raises(QueryTimeout) as raised:
        run_query(endless, con=con, timeout_seconds=0.5)

    assert raised.value.http_status == 504
    assert raised.value.details["timeout_seconds"] == 0.5
    # It really stopped, rather than being left to run while we returned.
    assert time.perf_counter() - started < 10


def test_the_connection_still_works_after_a_cancelled_query(con, endless, query, table):
    """A timeout that poisoned the connection would take every later question
    down with it."""
    with pytest.raises(QueryTimeout):
        run_query(endless, con=con, timeout_seconds=0.5)

    result = run_query(query(f"SELECT count(*) AS n FROM {table}"), con=con)
    assert result.rows == [[300]]


# --- failures ---------------------------------------------------------------


def test_a_query_that_fails_at_run_time_becomes_a_domain_error(con, loans):
    """Some SQL binds and still cannot run. Division by zero, a bad cast.

    Validation cannot catch these, so the executor has to turn them into
    something a caller can read.
    """
    sql = f'SELECT CAST("Branch Library" AS INTEGER) AS n FROM "{loans.table_name}"'
    with pytest.raises(QueryFailed) as raised:
        run_query(ValidatedQuery(sql=sql, tables=(loans.table_name,)), con=con)

    assert raised.value.code == "query_failed"
    assert "\n" not in raised.value.details["reason"]
