"""Running an evaluation suite and reporting what happened.

Two failures are counted separately on purpose, because they are not equally
bad:

* **Wrong answer.** The system produced a number that does not match the truth
  query. This is the failure the brief cares most about.
* **Wrong refusal.** The system refused a question the data can answer, or
  answered one it cannot. The second of those is the dangerous direction: it is
  the system inventing an answer.

A third bucket, **error**, covers the model producing SQL the validator rejects
or the database will not run. That is a malfunction rather than a wrong answer,
and lumping it in with wrong answers would hide it.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import duckdb

from ..answers import answer_question
from ..errors import InsightsError
from ..ingest.service import ingest_csv
from ..llm.base import LLMClient
from ..models.answer import Answer
from ..models.plan import PlanOutcome
from .suite import Case, Expectation, Suite


class Verdict(str, Enum):
    PASS = "pass"
    WRONG_ANSWER = "wrong answer"
    WRONG_REFUSAL = "wrong refusal"
    ANSWERED_THE_UNANSWERABLE = "answered the unanswerable"
    ERROR = "error"

    @property
    def ok(self) -> bool:
        return self is Verdict.PASS


@dataclass
class CaseResult:
    case: Case
    verdict: Verdict
    detail: str
    seconds: float
    sql: str | None = None

    @property
    def ok(self) -> bool:
        return self.verdict.ok


@dataclass
class SuiteResult:
    suite: Suite
    dataset_id: str
    results: list[CaseResult]
    skipped_reason: str | None = None

    @property
    def skipped(self) -> bool:
        return self.skipped_reason is not None

    @property
    def passed(self) -> int:
        return sum(1 for result in self.results if result.ok)

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def ok(self) -> bool:
        return self.passed == self.total


def run_suite(
    suite: Suite,
    *,
    con: duckdb.DuckDBPyConnection,
    client: LLMClient | None = None,
    repository_root: Path | None = None,
) -> SuiteResult:
    """Ingest the suite's CSV, then run every case against it.

    The file is ingested fresh each run rather than reusing a dataset that
    happens to be lying around, so a result can never depend on the state of
    somebody's warehouse.
    """
    root = repository_root or Path.cwd()
    csv_path = root / suite.csv

    # A suite may point at a file too large to commit. Missing input is a skip,
    # not a failure: nothing has been shown to be wrong.
    if not csv_path.exists():
        return SuiteResult(
            suite=suite,
            dataset_id="",
            results=[],
            skipped_reason=f"{suite.csv} is not present",
        )

    profile = ingest_csv(csv_path, con=con)

    results = [
        _run_case(
            case,
            dataset_id=profile.dataset_id,
            table_name=profile.table_name,
            con=con,
            client=client,
        )
        for case in suite.cases
    ]
    return SuiteResult(suite=suite, dataset_id=profile.dataset_id, results=results)


def _run_case(
    case: Case,
    *,
    dataset_id: str,
    table_name: str,
    con: duckdb.DuckDBPyConnection,
    client: LLMClient | None,
) -> CaseResult:
    started = time.perf_counter()
    try:
        answer = answer_question(dataset_id, case.question, con=con, client=client)
    except InsightsError as error:
        # The model produced something unusable. Not a wrong answer: a
        # malfunction, and counted as one.
        return CaseResult(
            case=case,
            verdict=Verdict.ERROR,
            detail=f"{error.code}: {error.message}",
            seconds=time.perf_counter() - started,
        )

    seconds = time.perf_counter() - started
    verdict, detail = _judge(case, answer, table_name=table_name, con=con)
    return CaseResult(
        case=case, verdict=verdict, detail=detail, seconds=seconds, sql=answer.sql
    )


def _judge(
    case: Case,
    answer: Answer,
    *,
    table_name: str,
    con: duckdb.DuckDBPyConnection,
) -> tuple[Verdict, str]:
    """Compare one answer to what the case expects."""
    refused = answer.outcome is PlanOutcome.REFUSAL

    if case.expect is Expectation.REFUSAL:
        if refused:
            return Verdict.PASS, answer.reason
        return (
            Verdict.ANSWERED_THE_UNANSWERABLE,
            f"expected a refusal, got SQL: {answer.sql}",
        )

    if refused:
        return Verdict.WRONG_REFUSAL, f"refused an answerable question: {answer.reason}"

    assert case.truth_sql is not None
    # The table name is generated at ingest time, so a suite writes {table}
    # and the harness fills it in. A suite therefore never names a table, which
    # is what lets the same suite run against a freshly ingested copy.
    truth = con.execute(truth_statement(case.truth_sql, table_name)).fetchall()

    if case.expect is Expectation.SCALAR:
        return _judge_scalar(case, answer, truth)
    return _judge_ranking(case, answer, truth)


def _judge_scalar(case: Case, answer: Answer, truth: list) -> tuple[Verdict, str]:
    """Compare one number.

    The model is free to return extra columns or name them differently, so the
    comparison takes the first numeric cell of the first row. What is being
    measured is whether it computed the right figure, not whether it labelled
    it the way we would have.
    """
    expected = _first_number(truth)
    actual = _first_number(answer.result.rows if answer.result else [])

    if expected is None:
        return Verdict.ERROR, "the truth query returned no number"
    if actual is None:
        return Verdict.WRONG_ANSWER, "the answer contained no number"

    if _close(actual, expected, case.tolerance):
        return Verdict.PASS, f"{actual:,.2f}"
    return Verdict.WRONG_ANSWER, f"expected {expected:,.2f}, got {actual:,.2f}"


def _judge_ranking(case: Case, answer: Answer, truth: list) -> tuple[Verdict, str]:
    """Compare an ordered list of labels.

    Only the first column is compared, and only as text. A ranking question is
    asking which things come out on top and in what order; the exact totals
    beside them are a separate concern, and insisting on both makes the check
    fail for reasons that are not about the ranking.
    """
    expected = [str(row[0]) for row in truth]
    actual = [str(row[0]) for row in (answer.result.rows if answer.result else [])]

    if actual == expected:
        return Verdict.PASS, f"{len(expected)} rows in the expected order"

    if sorted(actual) == sorted(expected):
        return Verdict.WRONG_ANSWER, "right rows, wrong order"

    return (
        Verdict.WRONG_ANSWER,
        f"expected {expected[:3]}... got {actual[:3]}...",
    )


def _first_number(rows: list) -> float | None:
    for row in rows:
        for value in row:
            if isinstance(value, bool):
                continue
            if isinstance(value, (int, float)):
                return float(value)
    return None


def _close(actual: float, expected: float, tolerance: float) -> bool:
    if expected == 0:
        return abs(actual) <= tolerance
    return abs(actual - expected) / abs(expected) <= tolerance


def truth_statement(truth_sql: str, table_name: str) -> str:
    """Fill the {table} placeholder a suite writes with the real table name."""
    return truth_sql.replace("{table}", f'"{table_name}"')
