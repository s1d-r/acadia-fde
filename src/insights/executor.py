"""Running a validated query, under limits.

The executor does not decide what is safe - it cannot be handed anything that
has not been through the validator, because it accepts a
:class:`~insights.validator.ValidatedQuery` and nothing else.

What it owns is the two limits that only exist at the moment of execution: how
many rows a caller may receive, and how long a query may run.
"""

from __future__ import annotations

import threading
import time

import duckdb

from .config import get_settings
from .errors import QueryFailed, QueryTimeout
from .models.answer import QueryResult
from .validator import ValidatedQuery
from .values import to_jsonable


def run_query(
    query: ValidatedQuery,
    *,
    con: duckdb.DuckDBPyConnection,
    max_rows: int | None = None,
    timeout_seconds: float | None = None,
) -> QueryResult:
    """Run ``query`` and return at most ``max_rows`` rows.

    The query runs on a worker thread so that the calling thread is free to stop
    it. DuckDB's ``interrupt`` is designed to be called from another thread and
    is scoped to the handle it is called on, so cancelling one question does not
    disturb any other question running at the same time - which is the whole
    reason every unit of work takes its own handle from ``db.session()``.
    """
    settings = get_settings()
    limit = max_rows if max_rows is not None else settings.max_result_rows
    timeout = (
        timeout_seconds
        if timeout_seconds is not None
        else settings.query_timeout_seconds
    )

    outcome: dict[str, object] = {}

    def work() -> None:
        try:
            cursor = con.execute(query.sql)
            # One row beyond the limit, purely to find out whether there were
            # more. Fetching a bounded number rather than everything means a
            # query matching a million rows costs us a thousand.
            outcome["rows"] = cursor.fetchmany(limit + 1)
            outcome["columns"] = [
                description[0] for description in cursor.description or []
            ]
        except duckdb.Error as exc:
            outcome["error"] = exc

    started = time.perf_counter()
    worker = threading.Thread(target=work, daemon=True, name="query")
    worker.start()
    worker.join(timeout)

    if worker.is_alive():
        con.interrupt()
        # The interrupt makes the running query raise, which lets the worker
        # finish. Joining again keeps this from leaking a thread per timeout.
        worker.join(settings.query_cancel_grace_seconds)
        raise QueryTimeout(
            "The query took too long and was cancelled",
            details={"timeout_seconds": timeout},
        )

    if "error" in outcome:
        exc = outcome["error"]
        assert isinstance(exc, duckdb.Error)
        raise QueryFailed(
            "The query could not be run against this dataset",
            details={"reason": str(exc).strip().splitlines()[0]},
        ) from exc

    duration_ms = int((time.perf_counter() - started) * 1000)
    fetched = outcome.get("rows") or []
    assert isinstance(fetched, list)
    truncated = len(fetched) > limit
    rows = fetched[:limit]

    return QueryResult(
        columns=list(outcome.get("columns") or []),
        rows=[[to_jsonable(value) for value in row] for row in rows],
        row_count=len(rows),
        truncated=truncated,
        duration_ms=duration_ms,
    )
