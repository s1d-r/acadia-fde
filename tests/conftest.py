"""Shared test setup.

Every test gets its own warehouse file in a temporary directory, so tests never
see each other's datasets and never touch the developer's ``data/`` directory.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from insights import db
from insights.config import get_settings

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def isolated_warehouse(tmp_path, monkeypatch):
    """Point the service at a throwaway database for the duration of one test."""
    monkeypatch.setenv("INSIGHTS_DATA_DIR", str(tmp_path / "data"))
    get_settings.cache_clear()
    db.close_connection()
    yield
    db.close_connection()
    get_settings.cache_clear()


@pytest.fixture
def con():
    """A connection to this test's warehouse."""
    return db.session()


@pytest.fixture
def profile_for(con):
    """Ingest a fixture file and return its profile.

    Goes through the real ingest path rather than constructing a profile by
    hand, so the context tests are exercising numbers that were actually
    measured from a file.
    """

    def build(filename: str):
        from insights.ingest.service import ingest_csv

        return ingest_csv(FIXTURES / filename, con=con)

    return build
