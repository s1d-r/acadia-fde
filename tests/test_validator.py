"""Tests for what the model is allowed to run.

This is the module that stands between a 7B model's output and the database, so
it is tested harder than anything else here. Two groups of tests matter most:

- the things that must be refused, including the ones a keyword scan would miss;
- the things that must be *accepted*, because a validator that rejects valid
  queries turns every awkwardly-named column into a failure.
"""

from __future__ import annotations

import pytest

from insights.context import build_context
from insights.errors import UnsafeQuery
from insights.ingest.service import ingest_csv
from insights.validator import ValidatedQuery, validate_sql

from .conftest import FIXTURES


@pytest.fixture
def loans(con):
    profile = ingest_csv(FIXTURES / "library_loans.csv", con=con)
    return build_context(profile)


@pytest.fixture
def check(con, loans):
    def run(sql: str) -> ValidatedQuery:
        return validate_sql(sql, context=loans, con=con)

    return run


@pytest.fixture
def table(loans):
    return f'"{loans.table_name}"'


# --- what must be accepted --------------------------------------------------


def test_a_plain_select_is_accepted(check, table):
    validated = check(f'SELECT "Branch Library" FROM {table}')
    assert validated.sql.startswith("SELECT")


def test_the_dataset_table_is_recorded(check, table, loans):
    assert check(f"SELECT * FROM {table}").tables == (loans.table_name,)


def test_aggregates_with_aliases_are_accepted(check, table):
    """An alias is not a column, and must not be mistaken for one."""
    check(
        f'SELECT "Branch Library", sum("Late Fee") AS total FROM {table} '
        "GROUP BY 1 ORDER BY total DESC"
    )


def test_a_cte_is_accepted(check, table, loans):
    """Half the interesting queries start with WITH, and a CTE name is a table
    reference that reads no data of its own."""
    validated = check(
        f'WITH per_branch AS (SELECT "Branch Library" AS b, count(*) AS n FROM {table} '
        "GROUP BY 1) SELECT b, n FROM per_branch ORDER BY n DESC"
    )
    # The CTE is not a data source, so it is not reported as one.
    assert validated.tables == (loans.table_name,)


def test_a_subquery_is_accepted(check, table):
    check(
        f'SELECT b FROM (SELECT "Branch Library" AS b FROM {table}) AS inner_query'
    )


def test_a_trailing_semicolon_is_stripped(check, table):
    assert not check(f"SELECT * FROM {table};").sql.endswith(";")


def test_a_semicolon_inside_a_string_is_not_a_second_statement(check, table):
    """The keyword scan this replaced rejected this query. DuckDB's parser knows
    a semicolon inside a literal does not end a statement."""
    check(f"""SELECT * FROM {table} WHERE "Branch Library" = 'Central;York'""")


def test_a_column_named_like_a_dangerous_keyword_is_accepted(con):
    """A fixture column is literally named ``drop table t; --``.

    A validator that reads text rather than parsing it rejects this, and then a
    perfectly ordinary file becomes unanswerable. Parsing is what makes the
    difference.
    """
    context = build_context(ingest_csv(FIXTURES / "awkward_names.csv", con=con))
    validated = validate_sql(
        f'SELECT "drop table t; --", "select" FROM "{context.table_name}"',
        context=context,
        con=con,
    )
    assert validated.tables == (context.table_name,)


# --- what must be refused: statement shape ----------------------------------


@pytest.mark.parametrize(
    "sql",
    [
        "DROP TABLE {t}",
        "DELETE FROM {t}",
        "INSERT INTO {t} VALUES (1)",
        "UPDATE {t} SET x = 1",
        "CREATE TABLE evil AS SELECT * FROM {t}",
        "ATTACH 'elsewhere.db'",
        "COPY {t} TO 'out.csv'",
        "PRAGMA database_list",
        "INSTALL httpfs",
        "SET memory_limit = '1GB'",
    ],
)
def test_anything_that_is_not_a_select_is_refused(check, table, sql):
    with pytest.raises(UnsafeQuery):
        check(sql.format(t=table))


def test_a_second_statement_is_refused(check, table):
    """The second statement is the one nobody inspected."""
    with pytest.raises(UnsafeQuery) as raised:
        check(f"SELECT * FROM {table}; DROP TABLE {table}")
    assert raised.value.details["statements"] == 2


def test_an_empty_query_is_refused(check):
    with pytest.raises(UnsafeQuery):
        check("   ")


def test_nonsense_is_refused_without_a_stack_trace(check):
    with pytest.raises(UnsafeQuery) as raised:
        check("this is not sql at all")
    assert raised.value.http_status == 400
    assert "\n" not in raised.value.details.get("reason", "")


# --- what must be refused: reading the wrong thing --------------------------


def test_reading_a_file_is_refused(check):
    """DuckDB will happily read the filesystem. This is the check that stops it."""
    with pytest.raises(UnsafeQuery) as raised:
        check("SELECT * FROM read_csv('/etc/passwd')")
    assert "files or table functions" in raised.value.message


def test_reading_a_parquet_file_is_refused(check):
    with pytest.raises(UnsafeQuery):
        check("SELECT * FROM read_parquet('secrets.parquet')")


def test_a_bare_file_path_is_refused(check):
    with pytest.raises(UnsafeQuery):
        check("SELECT * FROM 'secrets.csv'")


def test_a_table_function_is_refused(check):
    with pytest.raises(UnsafeQuery):
        check("SELECT * FROM range(100)")


def test_reading_our_own_bookkeeping_is_refused(check):
    """meta.datasets holds every dataset's profile. It is not answerable data."""
    with pytest.raises(UnsafeQuery) as raised:
        check("SELECT * FROM meta.datasets")
    assert "qualified" in raised.value.message


def test_reading_another_dataset_is_refused(con, loans):
    """Two files ingested, one question. It may only see its own."""
    other = ingest_csv(FIXTURES / "rentals.csv", con=con)

    with pytest.raises(UnsafeQuery) as raised:
        validate_sql(
            f'SELECT * FROM "{other.table_name}"', context=loans, con=con
        )
    assert raised.value.details["table"] == other.table_name


def test_joining_another_dataset_is_refused(con, loans):
    other = ingest_csv(FIXTURES / "rentals.csv", con=con)

    with pytest.raises(UnsafeQuery):
        validate_sql(
            f'SELECT * FROM "{loans.table_name}" CROSS JOIN "{other.table_name}"',
            context=loans,
            con=con,
        )


def test_a_query_that_reads_no_table_is_refused(check):
    """SELECT 1 is safe and answers nothing about the dataset."""
    with pytest.raises(UnsafeQuery) as raised:
        check("SELECT 1")
    assert "does not read the dataset" in raised.value.message


# --- what must be refused: columns that are not there -----------------------


def test_a_column_that_does_not_exist_is_refused(check, table):
    """The heart of "never invent a number": the binder resolves the name, and
    a name that is not there fails before anything runs."""
    with pytest.raises(UnsafeQuery) as raised:
        check(f'SELECT "Supplier Name" FROM {table}')
    assert raised.value.code == "unsafe_query"


def test_a_plausible_but_absent_column_is_refused(check, table):
    """The dangerous case: a name that sounds like it belongs to this file."""
    with pytest.raises(UnsafeQuery):
        check(f'SELECT sum("Late Fees") FROM {table}')


def test_a_column_that_does_not_exist_inside_a_cte_is_refused(check, table):
    with pytest.raises(UnsafeQuery):
        check(f'WITH x AS (SELECT "Nope" FROM {table}) SELECT * FROM x')


def test_validation_does_not_run_the_query(check, table, con):
    """Binding plans the statement and stops. If it executed, a validator would
    be a way to run a query without a row limit or a timeout."""
    import time

    started = time.perf_counter()
    check(
        f"SELECT count(*) FROM {table} a, {table} b, {table} c, {table} d "
        'WHERE hash(a."Days Kept" + d."Days Kept") % 7 = 0'
    )
    assert time.perf_counter() - started < 2.0


def test_a_file_is_refused_before_the_database_is_asked_about_it(check):
    """The order of the checks is load-bearing, so it is pinned here.

    Binding a query is not free of consequences: DuckDB opens a file named in
    read_csv to work out its columns, so asking the binder first would leak both
    whether a path exists and what is in it. The allowlist must run before the
    database sees the statement at all.

    Observable proof: pointed at a path that does not exist, the rejection is
    ours. If binding ran first, the error would be DuckDB's "No files found".
    """
    with pytest.raises(UnsafeQuery) as raised:
        check("SELECT * FROM read_csv('definitely_not_here_12345.csv')")

    assert "files or table functions" in raised.value.message
    assert "No files found" not in str(raised.value.details)
