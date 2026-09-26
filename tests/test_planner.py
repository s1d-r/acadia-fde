"""Tests for turning a question into a plan.

All of these run against a scripted client. Whether the real model is any good
is a different question, answered by the evaluation harness and by the
integration test that only runs when Ollama is up. What is tested here is that
*we* behave correctly whatever the model returns - including when it returns
nonsense, which it eventually will.
"""

from __future__ import annotations

import json

import pytest

from insights.context import build_context
from insights.errors import PlanningFailed
from insights.llm.fake import FakeLLMClient
from insights.models.plan import PlanOutcome
from insights.planner import PLAN_JSON_SCHEMA, SYSTEM_PROMPT, plan_query


@pytest.fixture
def context(profile_for):
    return build_context(profile_for("library_loans.csv"))


# --- the two good outcomes --------------------------------------------------


def test_a_usable_answer_becomes_a_query_plan(context):
    client = FakeLLMClient.answering(
        'SELECT count(*) FROM "t"', reason="Counts every loan."
    )
    plan = plan_query("How many loans are there?", context, client=client)

    assert plan.outcome is PlanOutcome.QUERY
    assert plan.sql == 'SELECT count(*) FROM "t"'
    assert plan.reason == "Counts every loan."
    assert plan.is_refusal is False


def test_a_refusal_is_an_outcome_not_an_error(context):
    """The whole design rests on this: refusing does not raise."""
    client = FakeLLMClient.refusing("There is no column recording a supplier.")
    plan = plan_query("Which supplier was slowest?", context, client=client)

    assert plan.outcome is PlanOutcome.REFUSAL
    assert plan.sql is None
    assert plan.reason == "There is no column recording a supplier."


def test_the_model_that_decided_is_recorded(context):
    plan = plan_query("q", context, client=FakeLLMClient.answering("SELECT 1"))
    assert plan.model == "fake"


# --- the model behaving badly but recoverably -------------------------------


def test_claiming_answerable_with_no_query_is_treated_as_a_refusal(context):
    """"Yes" followed by no SQL is not an answer.

    Passing an empty string to the executor would produce a database error the
    user cannot act on. The honest report is that we have no query.
    """
    client = FakeLLMClient.returning(
        json.dumps({"answerable": True, "sql": "   ", "reason": "I can do that."})
    )
    plan = plan_query("q", context, client=client)

    assert plan.outcome is PlanOutcome.REFUSAL
    assert plan.reason == "I can do that."


def test_a_refusal_with_no_reason_still_explains_itself(context):
    client = FakeLLMClient.returning(
        json.dumps({"answerable": False, "sql": "", "reason": ""})
    )
    plan = plan_query("q", context, client=client)

    assert plan.is_refusal
    assert plan.reason.strip()


def test_json_wrapped_in_a_code_fence_is_still_read(context):
    """Ollama constrains the output, but a different provider might not."""
    client = FakeLLMClient.returning(
        '```json\n{"answerable": true, "sql": "SELECT 1", "reason": "Ok then."}\n```'
    )
    plan = plan_query("q", context, client=client)

    assert plan.outcome is PlanOutcome.QUERY
    assert plan.sql == "SELECT 1"


# --- the model behaving badly, unrecoverably --------------------------------


def test_unparseable_output_is_a_domain_error_not_a_crash(context):
    client = FakeLLMClient.returning("I'm sorry, I can't help with that.")
    with pytest.raises(PlanningFailed) as raised:
        plan_query("q", context, client=client)

    assert raised.value.code == "planning_failed"
    assert raised.value.http_status == 502


def test_a_bad_response_is_quoted_back_but_not_in_full(context):
    client = FakeLLMClient.returning("x" * 5000)
    with pytest.raises(PlanningFailed) as raised:
        plan_query("q", context, client=client)

    received = raised.value.details["received"]
    assert len(received) <= 200


def test_json_that_is_not_an_object_is_rejected(context):
    client = FakeLLMClient.returning('["SELECT 1"]')
    with pytest.raises(PlanningFailed):
        plan_query("q", context, client=client)


def test_a_response_that_does_not_decide_is_rejected(context):
    """No "answerable" key means the model did not make the decision we asked
    for, and guessing which way it meant is exactly what must not happen."""
    client = FakeLLMClient.returning(json.dumps({"sql": "SELECT 1", "reason": "hi"}))
    with pytest.raises(PlanningFailed):
        plan_query("q", context, client=client)


def test_an_empty_question_never_reaches_the_model(context):
    client = FakeLLMClient([])
    with pytest.raises(PlanningFailed):
        plan_query("   ", context, client=client)
    assert client.calls == []


# --- what the model is actually told ----------------------------------------


def test_the_prompt_carries_the_schema_and_the_question(context):
    client = FakeLLMClient.answering("SELECT 1")
    plan_query("How many loans?", context, client=client)

    sent = client.calls[0]["user"]
    assert "How many loans?" in sent
    for name in context.column_names:
        assert f'"{name}"' in sent


def test_the_question_comes_last(context):
    """Models attend most reliably to the end of their input, and the question
    is the part that changes."""
    client = FakeLLMClient.answering("SELECT 1")
    plan_query("How many loans?", context, client=client)

    sent = client.calls[0]["user"]
    assert sent.index("How many loans?") > sent.index('"Loan Reference"')


def test_the_caveats_reach_the_model(profile_for):
    """A refusal is only possible if the model is told what is missing."""
    context = build_context(profile_for("awkward_names.csv"))
    client = FakeLLMClient.answering("SELECT 1")
    plan_query("Which month was busiest?", context, client=client)

    assert "no date or time column" in client.calls[0]["user"]


def test_the_output_shape_is_requested(context):
    client = FakeLLMClient.answering("SELECT 1")
    plan_query("q", context, client=client)

    assert client.calls[0]["json_schema"] == PLAN_JSON_SCHEMA
    assert client.calls[0]["system"] == SYSTEM_PROMPT


def test_the_reason_field_cannot_be_satisfied_by_an_empty_string():
    """The model returned "" here until the schema forbade it."""
    assert PLAN_JSON_SCHEMA["properties"]["reason"]["minLength"] > 0


def test_the_model_is_asked_to_decide_before_it_writes_sql():
    """Field order drives constrained decoding: state the plan, then write it."""
    fields = list(PLAN_JSON_SCHEMA["properties"])
    assert fields.index("answerable") < fields.index("reason") < fields.index("sql")
