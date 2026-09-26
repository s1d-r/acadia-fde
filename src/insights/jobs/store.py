"""Where jobs are kept.

In the same DuckDB file as the data, in the ``meta`` schema, next to the dataset
registry. One store, one thing to back up, one thing to inspect when something
has gone wrong.

Jobs are stored rather than held in memory for one reason: crash recovery. A
process that dies with three jobs running leaves three rows saying ``running``
that will never finish. On the next start those rows are marked failed, so a
client polling them is told the truth instead of waiting forever.
"""

from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone

import duckdb

from ..errors import InsightsError
from ..models.job import Job, JobError, JobKind, JobStatus

_JOBS_TABLE = "meta.jobs"

#: Writes to a job row are serialised in this process. DuckDB would serialise
#: them anyway, but a read-modify-write of a whole JSON document needs to be
#: atomic at our level, not just at the database's.
_write_lock = threading.Lock()


class JobNotFound(InsightsError):
    code = "job_not_found"
    http_status = 404


def ensure_schema(con: duckdb.DuckDBPyConnection) -> None:
    con.execute("CREATE SCHEMA IF NOT EXISTS meta")
    con.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_JOBS_TABLE} (
            job_id     VARCHAR PRIMARY KEY,
            kind       VARCHAR NOT NULL,
            status     VARCHAR NOT NULL,
            created_at TIMESTAMP NOT NULL,
            job_json   VARCHAR NOT NULL
        )
        """
    )


def new_job_id() -> str:
    return uuid.uuid4().hex


def create(
    kind: JobKind, *, con: duckdb.DuckDBPyConnection, dataset_id: str | None = None
) -> Job:
    """Record a queued job and return it."""
    job = Job(
        job_id=new_job_id(),
        kind=kind,
        status=JobStatus.QUEUED,
        created_at=datetime.now(timezone.utc),
        dataset_id=dataset_id,
    )
    save(job, con=con)
    return job


def save(job: Job, *, con: duckdb.DuckDBPyConnection) -> None:
    """Insert or replace a job row."""
    with _write_lock:
        ensure_schema(con)
        con.execute(
            f"""
            INSERT OR REPLACE INTO {_JOBS_TABLE}
                (job_id, kind, status, created_at, job_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                job.job_id,
                job.kind.value,
                job.status.value,
                job.created_at.astimezone(timezone.utc).replace(tzinfo=None),
                job.model_dump_json(),
            ],
        )


def get(job_id: str, *, con: duckdb.DuckDBPyConnection) -> Job:
    """Load one job, or raise :class:`JobNotFound`."""
    ensure_schema(con)
    row = con.execute(
        f"SELECT job_json FROM {_JOBS_TABLE} WHERE job_id = ?", [job_id]
    ).fetchone()
    if row is None:
        raise JobNotFound("No job with that id", details={"job_id": job_id})
    return Job.model_validate_json(row[0])


def mark_started(job: Job, *, con: duckdb.DuckDBPyConnection) -> Job:
    job.status = JobStatus.RUNNING
    job.started_at = datetime.now(timezone.utc)
    save(job, con=con)
    return job


def mark_succeeded(
    job: Job, result: dict, *, con: duckdb.DuckDBPyConnection
) -> Job:
    job.status = JobStatus.SUCCEEDED
    job.finished_at = datetime.now(timezone.utc)
    job.result = result
    save(job, con=con)
    return job


def mark_failed(job: Job, error: JobError, *, con: duckdb.DuckDBPyConnection) -> Job:
    job.status = JobStatus.FAILED
    job.finished_at = datetime.now(timezone.utc)
    job.error = error
    save(job, con=con)
    return job


def fail_interrupted_jobs(*, con: duckdb.DuckDBPyConnection) -> int:
    """Close out jobs left running by a process that died. Returns how many.

    Called once at startup. Any job still queued or running belongs to a
    previous process, because this one has not started any yet. Leaving them
    would mean a client polling a job that can never change.
    """
    ensure_schema(con)
    stale = con.execute(
        f"SELECT job_json FROM {_JOBS_TABLE} WHERE status IN (?, ?)",
        [JobStatus.QUEUED.value, JobStatus.RUNNING.value],
    ).fetchall()

    for (job_json,) in stale:
        job = Job.model_validate_json(job_json)
        mark_failed(
            job,
            JobError(
                code="interrupted",
                message="The service restarted while this job was running",
                details={},
            ),
            con=con,
        )
    return len(stale)
