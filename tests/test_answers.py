"""Tests for asking a question end to end.

Ingest a file, ask about it, get rows or a refusal. Still no network: the model
is scripted, so what is under test is the wiring between the pieces.
"""

from __future__ import annotations

import pytest

from insights.answers import answer_question
from insights.errors import DatasetNotFound, QueryFailed, UnsafeQuery
from insights.ingest.service import ingest_csv
from insights.llm.fake import FakeLLMClient
from insights.models.plan import PlanOutcome
from insights.sql_identifiers import quote_ident

from .conftest import FIXTURES


@pytest.fixture
def dataset(con):
    return ingest_csv(FIXTURES / "library_loans.csv", con=con)


def test_a_question_becomes_rows(con, dataset):
    table = quote_ident(dataset.table_name)
    client = FakeLLMClient.answering(
        f'SELECT "Branch Library", count(*) AS loans FROM {table} '
        'GROUP BY 1 ORDER BY loans DESC, 1',
        reason="Counts loans per branch.",
    )

    answer = answer_question(dataset.dataset_id, "Loans per branch?", con=con, client=client)

    assert answer.outcome is PlanOutcome.QUERY
    assert answer.result.columns == ["Branch Library", "loans"]
    assert answer.result.row_count == 4
    assert answer.reason == "Counts loans per branch."


def test_the_sql_is_part_of_the_answer(con, dataset):
    """A figure you cannot check is not a figure you can trust."""
    table = quote_ident(dataset.table_name)
    client = FakeLLMClient.answering(f"SELECT count(*) FROM {table}")

    answer = answer_question(dataset.dataset_id, "How many?", con=con, client=client)

    assert answer.sql is not None
    assert dataset.table_name in answer.sql
    assert answer.model == "fake"


def test_a_refusal_comes_back_as_an_answer(con, dataset):
    client = FakeLLMClient.refusing("There is no column recording a supplier.")

    answer = answer_question(dataset.dataset_id, "Which supplier?", con=con, client=client)

    assert answer.is_refusal
    assert answer.sql is None
    assert answer.result is None
    assert answer.reason == "There is no column recording a supplier."


def test_a_refusal_never_runs_anything(con, dataset):
    """A refusal that touched the database would be a refusal with a side
    effect, and the cost of a question we declined should be zero."""
    client = FakeLLMClient.refusing("Not answerable.")
    answer = answer_question(dataset.dataset_id, "?", con=con, client=client)

    assert answer.result is None


def test_asking_about_a_dataset_that_does_not_exist_is_a_bad_request(con):
    """Not a refusal: a refusal is about the data, and there is no data."""
    client = FakeLLMClient([])
    with pytest.raises(DatasetNotFound):
        answer_question("no-such-dataset", "anything", con=con, client=client)

    assert client.calls == []


def test_invented_sql_is_rejected_before_it_reaches_the_database(con, dataset):
    """The model's output goes through the validator on the way to the executor.

    A query naming a table and a column that do not exist never runs: it is
    refused by validation, not discovered at execution time.
    """
    client = FakeLLMClient.answering('SELECT "not_a_column" FROM "ds_nope"')

    with pytest.raises(UnsafeQuery):
        answer_question(dataset.dataset_id, "?", con=con, client=client)


def test_sql_that_binds_but_cannot_run_surfaces_as_a_query_failure(con, dataset):
    """Not everything can be caught before running. A cast that fails on the
    data is a failure, not a refusal: we said we could answer and then could
    not."""
    table = quote_ident(dataset.table_name)
    client = FakeLLMClient.answering(
        f'SELECT CAST("Branch Library" AS INTEGER) AS n FROM {table}'
    )

    with pytest.raises(QueryFailed):
        answer_question(dataset.dataset_id, "?", con=con, client=client)


def test_the_answer_serialises(con, dataset):
    table = quote_ident(dataset.table_name)
    client = FakeLLMClient.answering(f'SELECT min("Borrowed On") AS first FROM {table}')

    answer = answer_question(dataset.dataset_id, "?", con=con, client=client)
    rebuilt = type(answer).model_validate_json(answer.model_dump_json())

    assert rebuilt == answer
