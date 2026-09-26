"""Asking a question, end to end.

Load the dataset's profile, interpret it, plan, run, return. This is the
function the CLI calls today and the one the API and the job layer will call
later; none of them reimplement any of it.
"""

from __future__ import annotations

import duckdb

from . import db, registry
from .context import build_context
from .executor import run_query
from .llm import build_client
from .llm.base import LLMClient
from .models.answer import Answer
from .models.plan import PlanOutcome
from .planner.planner import plan_query
from .validator import validate_sql


def answer_question(
    dataset_id: str,
    question: str,
    *,
    con: duckdb.DuckDBPyConnection | None = None,
    client: LLMClient | None = None,
) -> Answer:
    """Answer ``question`` about ``dataset_id``, or explain why it cannot be.

    A refusal returns normally. The caller distinguishes the two by ``outcome``,
    not by catching an exception, because a refusal is a correct answer and
    exceptions are for things that went wrong.
    """
    connection = con if con is not None else db.session()
    llm = client if client is not None else build_client()

    # Raises DatasetNotFound, which the API maps to a 404. A question about a
    # dataset that does not exist is not a refusal; it is a bad request.
    profile = registry.get_profile(dataset_id, con=connection)
    context = build_context(profile)

    plan = plan_query(question, context, client=llm)

    if plan.is_refusal:
        return Answer(
            dataset_id=dataset_id,
            question=question,
            outcome=PlanOutcome.REFUSAL,
            reason=plan.reason,
            model=plan.model,
            planning_ms=plan.duration_ms,
        )

    assert plan.sql is not None  # guaranteed by plan_query for a query outcome

    # Nothing the model wrote reaches the database until this returns. The
    # executor accepts only what comes out of here, so the check cannot be
    # skipped by a future caller who forgets it exists.
    validated = validate_sql(plan.sql, context=context, con=connection)
    result = run_query(validated, con=connection)

    return Answer(
        dataset_id=dataset_id,
        question=question,
        outcome=PlanOutcome.QUERY,
        sql=plan.sql,
        reason=plan.reason,
        result=result,
        model=plan.model,
        planning_ms=plan.duration_ms,
    )
