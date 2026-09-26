"""Turning failures into responses.

One shape for every error the API can return:

```json
{"error": {"code": "dataset_not_found", "message": "...", "details": {}}}
```

A caller writes one piece of error handling, not one per endpoint. The ``code``
is stable and meant to be branched on; the ``message`` is meant to be read by a
person and may change.

Nothing here ever returns a traceback. An unexpected exception is logged in full
on the server and reported as a bare ``internal_error``, because a traceback
tells a caller nothing they can act on and can disclose paths and versions.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from ..errors import InsightsError

logger = logging.getLogger(__name__)


def error_body(code: str, message: str, details: dict | None = None) -> dict:
    return {"error": {"code": code, "message": message, "details": details or {}}}


def install_error_handlers(app: FastAPI) -> None:
    """Register the handlers. Called once, when the app is built."""

    @app.exception_handler(InsightsError)
    async def _domain_error(_: Request, error: InsightsError) -> JSONResponse:
        # Every expected failure in this system is an InsightsError and already
        # carries the status code it should produce.
        return JSONResponse(
            status_code=error.http_status,
            content=error_body(error.code, error.message, error.details),
        )

    @app.exception_handler(RequestValidationError)
    async def _bad_request(_: Request, error: RequestValidationError) -> JSONResponse:
        # FastAPI's own validation, reshaped into our envelope. The field level
        # detail is kept, because "which field" is exactly what a caller needs.
        return JSONResponse(
            status_code=422,
            content=error_body(
                "invalid_request",
                "The request did not match what this endpoint expects",
                {"fields": _readable_fields(error)},
            ),
        )

    @app.exception_handler(HTTPException)
    async def _http_error(_: Request, error: HTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=error.status_code,
            content=error_body(_code_for_status(error.status_code), str(error.detail)),
        )

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, error: Exception) -> JSONResponse:
        logger.exception("Unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content=error_body(
                "internal_error", "Something went wrong handling this request"
            ),
        )


def _readable_fields(error: RequestValidationError) -> list[dict]:
    """Flatten Pydantic's error list into something a human can read."""
    fields = []
    for item in error.errors():
        location = [str(part) for part in item.get("loc", []) if part != "body"]
        fields.append(
            {"field": ".".join(location) or "body", "problem": item.get("msg", "")}
        )
    return fields


def _code_for_status(status: int) -> str:
    return {
        400: "bad_request",
        404: "not_found",
        405: "method_not_allowed",
        413: "payload_too_large",
        415: "unsupported_media_type",
    }.get(status, "http_error")
