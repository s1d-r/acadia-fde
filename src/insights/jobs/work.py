"""What each kind of job actually does.

Thin by design. Each one calls the same function the command line calls, then
returns a plain dictionary for the job store to keep. No business logic lives
here, so nothing about answering a question depends on having been asked
through a job.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import duckdb

from ..answers import answer_question
from ..ingest.service import ingest_csv
from ..llm.base import LLMClient
from ..models.job import Job
from .runner import JobWork


def ingest_job(path: Path, *, original_filename: str) -> JobWork:
    """Build the work function for ingesting one uploaded file."""

    def work(con: duckdb.DuckDBPyConnection, job: Job) -> dict[str, Any]:
        profile = ingest_csv(path, original_filename=original_filename, con=con)
        # Recorded on the job so a caller polling an upload can follow the
        # dataset id without parsing the result body.
        job.dataset_id = profile.dataset_id
        return profile.model_dump(mode="json")

    return work


def question_job(
    dataset_id: str, question: str, *, client: LLMClient | None = None
) -> JobWork:
    """Build the work function for answering one question."""

    def work(con: duckdb.DuckDBPyConnection, job: Job) -> dict[str, Any]:
        answer = answer_question(dataset_id, question, con=con, client=client)
        return answer.model_dump(mode="json")

    return work
