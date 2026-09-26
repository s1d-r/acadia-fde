"""Running jobs in the background.

A fixed pool of worker threads inside the API process. Not Celery, not a queue
server, not a second container. The reasons are in `docs/system-design.md`, and
the short version is that DuckDB allows one writing process, so a separate
worker process could not write to the same file anyway.

Threads rather than processes is therefore not a shortcut. It is the only shape
that fits the storage engine, and it works because the two slow things here both
release the interpreter lock: DuckDB runs queries in its own C++ threads, and
the model call is waiting on a socket.
"""

from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

import duckdb

from .. import db
from ..config import get_settings
from ..errors import InsightsError
from ..models.job import Job, JobError, JobKind
from . import store

logger = logging.getLogger(__name__)

#: A job's work function. It is given its own database handle, because a handle
#: must not be shared between threads.
JobWork = Callable[[duckdb.DuckDBPyConnection, Job], dict[str, Any]]


class JobRunner:
    """Submits work to a bounded pool and records what happened."""

    def __init__(self, *, max_workers: int | None = None) -> None:
        settings = get_settings()
        self._max_workers = max_workers or settings.job_workers
        # Bounded on purpose. Unbounded concurrency against a single DuckDB
        # file turns a burst of questions into a queue at the storage layer
        # instead of a queue we can see and reason about.
        self._pool = ThreadPoolExecutor(
            max_workers=self._max_workers, thread_name_prefix="job"
        )
        self._lock = threading.Lock()
        self._closed = False

    @property
    def max_workers(self) -> int:
        return self._max_workers

    def submit(
        self,
        kind: JobKind,
        work: JobWork,
        *,
        dataset_id: str | None = None,
    ) -> Job:
        """Record a queued job, hand it to the pool, and return it at once.

        The job row is written before the work is queued. If it were written
        afterwards, a caller could be handed an id that does not yet exist and
        get a 404 for their first poll.
        """
        with self._lock:
            if self._closed:
                raise RuntimeError("The job runner is shut down")
            job = store.create(kind, con=db.session(), dataset_id=dataset_id)
            self._pool.submit(self._run, job, work)
        return job

    def _run(self, job: Job, work: JobWork) -> None:
        """Run one job. This is the only code on a worker thread."""
        # Its own handle, created on this thread. Sharing one between threads
        # would mean two jobs reading each other's rows.
        con = db.session()
        try:
            store.mark_started(job, con=con)
            result = work(con, job)
            store.mark_succeeded(job, result, con=con)
        except InsightsError as error:
            # An expected failure. The caller gets the same structured error
            # they would have got from a synchronous call.
            store.mark_failed(
                job,
                JobError(
                    code=error.code, message=error.message, details=error.details
                ),
                con=con,
            )
        except Exception:
            # An unexpected failure is a bug. It is logged in full here and
            # reported to the caller as a bare code, because a traceback is not
            # something a caller can act on and may say more than it should.
            logger.exception("Job %s failed unexpectedly", job.job_id)
            store.mark_failed(
                job,
                JobError(
                    code="internal_error",
                    message="The job failed unexpectedly",
                    details={},
                ),
                con=con,
            )

    def shutdown(self, *, wait: bool = True) -> None:
        with self._lock:
            self._closed = True
        self._pool.shutdown(wait=wait)
