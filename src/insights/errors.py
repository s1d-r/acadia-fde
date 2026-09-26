"""Domain errors.

Every failure the engine can produce on purpose is one of these. Each carries a
stable machine-readable ``code`` and the HTTP status the API layer should use,
so the API layer can turn any of them into a structured error response without
knowing what went wrong or leaking a traceback.
"""

from __future__ import annotations

from typing import Any


class InsightsError(Exception):
    """Base class for expected failures. Anything else is a bug."""

    code: str = "internal_error"
    http_status: int = 500

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details: dict[str, Any] = details or {}

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "details": self.details}


class InvalidFile(InsightsError):
    """The uploaded file is not something we are willing to try to read."""

    code = "invalid_file"
    http_status = 400


class IngestionError(InsightsError):
    """The file was readable but could not be turned into a usable table."""

    code = "ingestion_failed"
    http_status = 400


class DatasetNotFound(InsightsError):
    """No dataset with that id has been ingested."""

    code = "dataset_not_found"
    http_status = 404


class LLMUnavailable(InsightsError):
    """The model could not be reached, or did not answer in time."""

    code = "llm_unavailable"
    http_status = 503


class PlanningFailed(InsightsError):
    """The model was reached but returned something we cannot use."""

    code = "planning_failed"
    http_status = 502


class UnsafeQuery(InsightsError):
    """The generated SQL is not something we are willing to run."""

    code = "unsafe_query"
    http_status = 400


class QueryFailed(InsightsError):
    """The SQL was accepted but the database refused to run it."""

    code = "query_failed"
    http_status = 400


class QueryTimeout(InsightsError):
    """The query ran longer than the service allows and was cancelled."""

    code = "query_timeout"
    http_status = 504
