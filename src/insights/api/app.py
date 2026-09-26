"""The HTTP API.

Thin on purpose. Every endpoint does the same three things: check the input,
call something in the engine, serialise what comes back. There is no business
logic here, which is why the command line and the API give identical answers.

Slow work is not done here. Uploading a file and asking a question both return
202 with a job id, and the caller polls. See `docs/system-design.md`.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, FastAPI, Request, UploadFile
from fastapi.responses import FileResponse

from .. import db, registry
from ..config import get_settings
from ..context import build_context, render_for_prompt
from ..errors import InvalidFile
from ..jobs import JobRunner, ingest_job, question_job
from ..jobs import store as job_store
from ..models.job import Job, JobKind
from ..sql_identifiers import new_dataset_id
from .errors import install_error_handlers
from .schemas import AskRequest, DatasetList, JobAccepted, JobView, SchemaContextView

logger = logging.getLogger(__name__)

UI_DIRECTORY = Path(__file__).resolve().parent.parent / "ui"

#: Extensions we will try to read. Not a security control: the content is what
#: matters and DuckDB decides that. It is here to catch the ordinary mistake of
#: uploading a spreadsheet or a zip and getting a confusing parse error back.
ALLOWED_SUFFIXES = {".csv", ".tsv", ".txt"}


def create_app() -> FastAPI:
    """Build the application.

    A function rather than a module level object, so a test can build one per
    test against its own temporary database, and so two apps in one process
    never share a job pool.
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        settings = get_settings()
        settings.upload_dir.mkdir(parents=True, exist_ok=True)

        # Any job still marked running belongs to a process that died, because
        # this one has not started any yet. Close them out, so nobody polls a
        # job that can never change.
        recovered = job_store.fail_interrupted_jobs(con=db.session())
        if recovered:
            logger.warning("Marked %d interrupted job(s) as failed", recovered)

        app.state.runner = JobRunner()
        try:
            yield
        finally:
            app.state.runner.shutdown(wait=False)
            db.close_connection()

    app = FastAPI(
        title="Natural Language Insights Engine",
        version="0.1.0",
        summary="Ask questions in plain English about any transactional CSV.",
        lifespan=lifespan,
    )
    install_error_handlers(app)
    app.include_router(_router())
    return app


def _router() -> APIRouter:
    router = APIRouter()

    # --- the page ---------------------------------------------------------

    @router.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(UI_DIRECTORY / "index.html")

    @router.get("/health", tags=["service"])
    async def health() -> dict:
        """Cheap liveness check. Does not touch the model or the database."""
        return {"status": "ok"}

    # --- datasets ---------------------------------------------------------

    @router.post(
        "/api/datasets", status_code=202, response_model=JobAccepted, tags=["datasets"]
    )
    async def upload_dataset(request: Request, file: UploadFile) -> JobAccepted:
        """Accept a CSV and start ingesting it.

        Returns at once with a job id. Reading and profiling half a million rows
        takes seconds, which is too long to hold a request open.
        """
        saved = _save_upload(file)
        job = _runner(request).submit(
            JobKind.INGEST,
            ingest_job(saved, original_filename=file.filename or saved.name),
        )
        return JobAccepted(job_id=job.job_id, status=job.status)

    @router.get("/api/datasets", response_model=DatasetList, tags=["datasets"])
    async def list_datasets() -> DatasetList:
        return DatasetList(datasets=registry.list_datasets(con=db.session()))

    @router.get("/api/datasets/{dataset_id}", tags=["datasets"])
    async def get_dataset(dataset_id: str) -> dict:
        """The full measured profile of one dataset."""
        profile = registry.get_profile(dataset_id, con=db.session())
        return profile.model_dump(mode="json")

    @router.get(
        "/api/datasets/{dataset_id}/context",
        response_model=SchemaContextView,
        tags=["datasets"],
    )
    async def get_dataset_context(dataset_id: str) -> SchemaContextView:
        """The schema description the planner is given, and its text form.

        Exposed because it is the most useful thing to look at when an answer
        is wrong. It is everything the model knew.
        """
        profile = registry.get_profile(dataset_id, con=db.session())
        context = build_context(profile)
        return SchemaContextView(
            context=context, prompt_text=render_for_prompt(context)
        )

    # --- questions --------------------------------------------------------

    @router.post(
        "/api/datasets/{dataset_id}/questions",
        status_code=202,
        response_model=JobAccepted,
        tags=["questions"],
    )
    async def ask(request: Request, dataset_id: str, body: AskRequest) -> JobAccepted:
        """Ask a question about a dataset.

        Returns a job id. The model takes seconds to plan, and a request that
        waits for it is a request that times out somewhere else.

        The dataset is looked up here rather than in the worker, so that a bad
        id is a 404 now instead of a job that fails a moment later.
        """
        registry.get_profile(dataset_id, con=db.session())

        job = _runner(request).submit(
            JobKind.QUESTION,
            question_job(dataset_id, body.question),
            dataset_id=dataset_id,
        )
        return JobAccepted(job_id=job.job_id, status=job.status)

    # --- jobs -------------------------------------------------------------

    @router.get("/api/jobs/{job_id}", response_model=JobView, tags=["jobs"])
    async def get_job(job_id: str) -> Job:
        """Poll a job. Carries the result once there is one."""
        return job_store.get(job_id, con=db.session())

    return router


def _runner(request: Request) -> JobRunner:
    """The pool built at startup, reached through the running application."""
    return request.app.state.runner


def _save_upload(file: UploadFile) -> Path:
    """Stream an upload to disk, refusing anything too large.

    Written in chunks and checked as it goes, so a caller cannot make the
    service buy a gigabyte of memory by claiming a small file and sending a
    large one. The name on disk comes from a generated id, never from the
    uploaded filename.
    """
    settings = get_settings()
    name = Path(file.filename or "upload.csv").name
    suffix = Path(name).suffix.lower()

    if suffix not in ALLOWED_SUFFIXES:
        raise InvalidFile(
            "Only CSV files are accepted",
            details={"filename": name, "accepted": sorted(ALLOWED_SUFFIXES)},
        )

    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    destination = settings.upload_dir / f"{new_dataset_id()}{suffix}"

    written = 0
    limit = settings.max_csv_bytes
    try:
        with destination.open("wb") as handle:
            while chunk := file.file.read(1024 * 1024):
                written += len(chunk)
                if written > limit:
                    raise InvalidFile(
                        "The file is larger than this service accepts",
                        details={"limit_bytes": limit},
                    )
                handle.write(chunk)

        if written == 0:
            raise InvalidFile("The file is empty", details={"filename": name})
    except BaseException:
        destination.unlink(missing_ok=True)
        raise

    return destination
