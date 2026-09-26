"""Deciding whether generated SQL may run.

The model is not trusted. Not because it is malicious, but because it is a 7B
model doing a hard task, and because the difference between a system you can put
in front of a merchandising team and a demo is what happens on the day it gets
something wrong.

Four checks, and the important thing about them is that each is done by whatever
is *best able* to do it rather than by code written here:

1. **Is it one statement, and is it a SELECT?** Answered by DuckDB's own parser.
   A keyword scan - what slice 3 used - reads text rather than understanding it,
   and can be fooled by a keyword in a string literal or a column name.
2. **Does it read only the table we described?** Answered by parsing the
   statement with sqlglot and checking every table reference against an
   allowlist. This is the check nothing else will do for us: DuckDB is
   perfectly happy to read another dataset's table, our own bookkeeping, or a
   file off the disk.
3. **Do the columns exist?** Answered by DuckDB's binder, via ``EXPLAIN``. The
   binder already resolves aliases, subqueries and CTEs correctly. Re-deriving
   that here would mean re-implementing SQL name resolution, and getting it
   subtly wrong.
4. **Does it finish?** Not answered here. That is a limit at execution time and
   belongs in the executor with the row limit.

The output is a :class:`ValidatedQuery`. The executor accepts nothing else, so
unvalidated SQL cannot reach the database by mistake: the type is the guarantee.
"""

from __future__ import annotations

from dataclasses import dataclass

import duckdb
import sqlglot
from sqlglot import exp

from .errors import UnsafeQuery
from .models.context import SchemaContext


@dataclass(frozen=True)
class ValidatedQuery:
    """SQL that has passed every check in this module.

    Only :func:`validate_sql` should construct one. The executor requires one,
    which is what stops raw model output reaching the database.
    """

    sql: str
    tables: tuple[str, ...]


def validate_sql(
    sql: str,
    *,
    context: SchemaContext,
    con: duckdb.DuckDBPyConnection,
) -> ValidatedQuery:
    """Check ``sql`` against ``context``, or raise :class:`UnsafeQuery`."""
    statement = sql.strip().rstrip(";").strip()
    if not statement:
        raise UnsafeQuery("The query is empty")

    # The order matters and is not arbitrary. The table allowlist runs *before*
    # the database is asked to bind the statement, because binding a query is
    # not free of consequences: planning `SELECT * FROM read_csv('/etc/passwd')`
    # makes DuckDB open that file to work out its columns. Checking what may be
    # read has to happen before anything is read.
    _assert_single_select(statement)
    tables = _assert_known_tables(statement, context)
    _assert_columns_resolve(statement, con=con)

    return ValidatedQuery(sql=statement, tables=tables)


def _assert_single_select(statement: str) -> None:
    """One statement, and a reading one.

    DuckDB's parser decides both. It knows that the semicolon inside
    ``WHERE note = 'a;b'`` does not start a second statement, and that
    ``SELECT`` is what a SELECT looks like however it is spelled or spaced.
    """
    try:
        parsed = duckdb.extract_statements(statement)
    except duckdb.Error as exc:
        raise UnsafeQuery(
            "The query is not valid SQL",
            details={"reason": _first_line(exc)},
        ) from exc

    if len(parsed) != 1:
        raise UnsafeQuery(
            "Only one statement may be run",
            details={"statements": len(parsed)},
        )

    kind = parsed[0].type
    # Compared with ``==`` and not ``is``. DuckDB's StatementType is a pybind11
    # enum, not a Python one: each attribute access hands back a fresh object,
    # so ``is`` is always False and an identity check silently rejects every
    # query. ``is`` is the idiomatic choice for enums, which is exactly why this
    # comment is here.
    if kind != duckdb.StatementType.SELECT:
        raise UnsafeQuery(
            "Only SELECT queries may be run",
            details={"statement_type": str(kind).removeprefix("StatementType.")},
        )


def _assert_known_tables(statement: str, context: SchemaContext) -> tuple[str, ...]:
    """Every table read must be the dataset's table, or a CTE defined inline.

    An allowlist rather than a list of forbidden things. A denylist would have
    to anticipate every way DuckDB can be pointed at data - ``read_csv``,
    ``read_parquet``, a bare file path, a schema-qualified name, an extension
    installed later - and it only has to be incomplete once.
    """
    try:
        tree = sqlglot.parse_one(statement, dialect="duckdb")
    except sqlglot.ParseError as exc:
        raise UnsafeQuery(
            "The query could not be parsed",
            details={"reason": str(exc).strip().splitlines()[0]},
        ) from exc

    # A CTE name is a legitimate thing to select from: it is defined in the
    # statement itself and reads no data of its own.
    defined_here = {cte.alias_or_name for cte in tree.find_all(exp.CTE)}
    allowed = {context.table_name} | defined_here

    found: list[str] = []
    for table in tree.find_all(exp.Table):
        if not isinstance(table.this, exp.Identifier):
            # read_csv('/etc/passwd'), read_parquet(...), range(...) - anything
            # that produces rows from somewhere other than a named table.
            raise UnsafeQuery(
                "Queries may only read the dataset's table, not files or table functions",
                details={"source": table.sql(dialect="duckdb")[:120]},
            )

        if table.db or table.catalog:
            # Blocks meta.datasets, and any other schema we keep to ourselves.
            raise UnsafeQuery(
                "Table names may not be qualified with a schema or database",
                details={"source": table.sql(dialect="duckdb")[:120]},
            )

        if table.name not in allowed:
            raise UnsafeQuery(
                "The query refers to a table that is not this dataset",
                details={"table": table.name, "expected": context.table_name},
            )

        if table.name not in defined_here:
            found.append(table.name)

    if not found:
        # Every question is answered from the dataset. A query that reads no
        # table at all - SELECT 1 - answers nothing about it.
        raise UnsafeQuery(
            "The query does not read the dataset",
            details={"expected": context.table_name},
        )

    return tuple(dict.fromkeys(found))


def _assert_columns_resolve(statement: str, *, con: duckdb.DuckDBPyConnection) -> None:
    """Ask the database to bind the query without running it.

    ``EXPLAIN`` plans a statement and stops. It resolves every column, alias and
    CTE exactly as execution would, and fails the same way on a name that is not
    there - which is precisely the check we want and the one hardest to write
    correctly by hand. It is also cheap: planning a query over a billion rows
    takes single-digit milliseconds, because it does not touch them.
    """
    try:
        con.execute(f"EXPLAIN {statement}").fetchall()
    except duckdb.Error as exc:
        # Most often a column that does not exist, which is the case this
        # check is here for. It also catches a type error or an unknown
        # function, so the message stays general and the binder's own words go
        # in the details rather than being paraphrased into something wrong.
        raise UnsafeQuery(
            "The query could not be resolved against this dataset",
            details={"reason": _first_line(exc)},
        ) from exc


def _first_line(error: Exception) -> str:
    return str(error).strip().splitlines()[0]
