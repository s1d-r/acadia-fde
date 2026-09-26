"""Smoke tests against the real model.

Excluded from the default run and from CI, because they need a model server and
they are slow. Run them with ``pytest -m integration``.

These check that the real client and the real constrained-decoding path work at
all - that we speak the server's protocol correctly and get something shaped
like a decision back. Whether the model's SQL is *right* is measured by the
evaluation harness, not asserted here: a test that fails when a 7B model has an
off day is a test nobody will trust or fix.
"""

from __future__ import annotations

import httpx
import pytest

from insights.answers import answer_question
from insights.config import get_settings
from insights.ingest.service import ingest_csv
from insights.llm import build_client
from insights.models.plan import PlanOutcome

from .conftest import FIXTURES

pytestmark = pytest.mark.integration


def _server_is_up() -> bool:
    settings = get_settings()
    try:
        response = httpx.get(f"{settings.ollama_host}/api/tags", timeout=2.0)
        models = [model["name"] for model in response.json().get("models", [])]
    except (httpx.HTTPError, ValueError, KeyError):
        return False
    return settings.ollama_model in models


requires_ollama = pytest.mark.skipif(
    not _server_is_up(), reason="no Ollama server with the configured model"
)


@pytest.fixture
def dataset(con):
    return ingest_csv(FIXTURES / "library_loans.csv", con=con)


@requires_ollama
def test_the_real_model_returns_a_usable_decision(con, dataset):
    answer = answer_question(
        dataset.dataset_id,
        "How many loans were there at each branch?",
        con=con,
        client=build_client(),
    )

    assert answer.outcome is PlanOutcome.QUERY
    assert answer.sql
    assert answer.result is not None
    assert answer.result.row_count > 0
    # The constraint the schema imposes on every response.
    assert len(answer.reason) >= 15


@requires_ollama
def test_the_real_model_refuses_what_the_file_cannot_answer(con, dataset):
    """There is nothing in a loans file about what a book cost to buy."""
    answer = answer_question(
        dataset.dataset_id,
        "Which publisher charged us the most for these books?",
        con=con,
        client=build_client(),
    )

    assert answer.is_refusal
    assert answer.reason


@requires_ollama
def test_the_real_model_reaches_for_the_date_column_for_a_period_question(con, dataset):
    """It refused this kind of question until the prompt said a temporal column
    can be grouped into periods."""
    answer = answer_question(
        dataset.dataset_id,
        "How many loans were there in March 2022?",
        con=con,
        client=build_client(),
    )

    assert answer.outcome is PlanOutcome.QUERY
    assert "Borrowed On" in (answer.sql or "")
