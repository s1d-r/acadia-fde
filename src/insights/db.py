"""DuckDB connection management.

DuckDB is an in-process engine backed by a single file. One process may hold
the write lock, and within that process concurrent work is done by taking a
*cursor* off the one connection. A cursor is an independent handle that shares
the same database and buffer pool, and is safe to use from another thread.

So: one connection per process, created lazily, and :func:`session` for every
unit of work.
"""

from __future__ import annotations

import threading

import duckdb

from .config import get_settings

_connection: duckdb.DuckDBPyConnection | None = None
_connection_lock = threading.Lock()


def get_connection() -> duckdb.DuckDBPyConnection:
    """Return the process-wide connection, opening it on first use."""
    global _connection
    with _connection_lock:
        if _connection is None:
            settings = get_settings()
            settings.database_file.parent.mkdir(parents=True, exist_ok=True)
            _connection = duckdb.connect(str(settings.database_file))
        return _connection


def session() -> duckdb.DuckDBPyConnection:
    """A short-lived handle for one unit of work.

    Always take one of these rather than sharing the root connection: results
    and prepared statements live on the handle, so two threads sharing one
    would read each other's rows.
    """
    return get_connection().cursor()


def close_connection() -> None:
    """Close the connection. Used by tests and on shutdown."""
    global _connection
    with _connection_lock:
        if _connection is not None:
            _connection.close()
            _connection = None
