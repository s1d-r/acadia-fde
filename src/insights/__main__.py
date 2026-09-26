"""Run the service with `python -m insights`.

A module entry point rather than a shell script, so the same command works on
Windows, macOS and Linux without a second file to keep in step.
"""

from __future__ import annotations

import uvicorn

from .config import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "insights.api:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
