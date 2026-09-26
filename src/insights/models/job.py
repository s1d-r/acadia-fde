"""Jobs.

Ingesting a 500,000 row file takes seconds. Asking a question takes as long as
the model takes to think. Neither should be done while an HTTP client holds a
socket open, so both are submitted as jobs: the caller gets an id straight away
and polls for the outcome.

A job is a small record with a status and, once it is over, either a result or
an error. It is deliberately not a stream of progress events. The work here has
no meaningful progress to report between "started" and "finished", and a
progress bar that moves for no reason is a lie.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class JobKind(str, Enum):
    """What a job is doing. Used for reporting, never for dispatch."""

    INGEST = "ingest"
    QUESTION = "question"


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"

    @property
    def is_finished(self) -> bool:
        return self in (JobStatus.SUCCEEDED, JobStatus.FAILED)


class JobError(BaseModel):
    """Why a job failed, in the same shape the API uses for every other error.

    A caller polling a job should not have to parse a second error format.
    """

    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class Job(BaseModel):
    """One unit of background work."""

    job_id: str
    kind: JobKind
    status: JobStatus

    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None

    dataset_id: str | None = Field(
        default=None,
        description="Set as soon as it is known, so a caller polling an "
        "ingestion can see which dataset it produced.",
    )

    result: dict[str, Any] | None = Field(
        default=None,
        description="The profile for an ingest, the answer for a question. "
        "Stored as a plain object so the job store never needs to know which.",
    )
    error: JobError | None = None

    @property
    def is_finished(self) -> bool:
        return self.status.is_finished
