"""Safe SQL identifier handling.

Column names come from a file we have never seen. They can contain spaces,
quotes, unicode, or a word DuckDB treats as reserved. Every identifier that
reaches a SQL string goes through :func:`quote_ident` first.
"""

from __future__ import annotations

import re
import uuid

#: Table names we generate ourselves. Restricted to characters that cannot mean
#: anything in SQL, so a generated name can never carry an injection.
_SAFE_TABLE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def quote_ident(name: str) -> str:
    """Quote an identifier for DuckDB.

    Double quotes delimit identifiers in SQL; a literal double quote inside one
    is escaped by doubling it. That makes any string safe to use as a name.
    """
    return '"' + name.replace('"', '""') + '"'


def new_dataset_id() -> str:
    """A fresh dataset id: 32 hex characters, no dashes."""
    return uuid.uuid4().hex


def table_name_for(dataset_id: str) -> str:
    """Map a dataset id to the table that holds its rows.

    The table name is derived from an id we generated, never from the uploaded
    filename, so user input never reaches a table name.
    """
    name = f"ds_{dataset_id}"
    if not _SAFE_TABLE_NAME.match(name):
        raise ValueError(f"refusing to build a table name from {dataset_id!r}")
    return name
