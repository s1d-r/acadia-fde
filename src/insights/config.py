"""Runtime configuration.

Everything tunable lives here, read from environment variables prefixed with
``INSIGHTS_`` (or a local ``.env``). Nothing here describes a dataset: no column
names, no table names, no business meaning. Only how the service behaves.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="INSIGHTS_", env_file=".env", extra="ignore"
    )

    #: Directory holding the DuckDB file and any saved uploads.
    data_dir: Path = Path("data")

    #: Largest CSV we will accept, in bytes. A guard at the boundary so a huge
    #: upload fails fast with a clear message instead of filling the disk.
    max_csv_bytes: int = 1_000_000_000

    #: How many frequent values per column the profiler keeps. These end up in
    #: the prompt, so the number trades schema fidelity against token cost.
    sample_values_per_column: int = 5

    #: Longest sample value we keep, in characters. Free-text columns can hold
    #: paragraphs; we only need enough to recognise the format.
    sample_value_max_chars: int = 120

    # --- Thresholds for inferring a column's role -------------------------
    # These are judgement calls, so they are configuration rather than
    # constants buried in the code. Every one of them is about shape, never
    # about a particular dataset.

    #: Distinct values over non-null values, above which a column names a row
    #: rather than a group. Not 1.0, because a near-key with a handful of
    #: duplicates is still an identifier.
    identifier_distinct_rate: float = 0.95

    #: Fewest non-null values before the distinct rate is believed at all. Over
    #: five rows, "every value is distinct" is a coincidence; over five hundred
    #: it is a key.
    identifier_min_values: int = 20

    #: At or below this many distinct values, a text column is something to
    #: group by rather than a code.
    category_max_distinct: int = 50

    #: Mean characters above which a text column reads as prose, not a label.
    free_text_mean_length: float = 40.0

    #: A single very long value also marks a column as prose.
    free_text_max_length: int = 200

    #: Null rate at or above which a column is called out as mostly empty.
    high_null_rate: float = 0.5

    #: Most columns to describe in a prompt. A very wide file would otherwise
    #: produce a context larger than the model's window.
    max_context_columns: int = 150

    # --- The language model -----------------------------------------------

    #: Which implementation of the LLM client to build. The planner never sees
    #: this; it is given a client and does not know where it came from.
    llm_provider: str = "ollama"

    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5-coder:7b"

    #: Zero, so the same question against the same data gives the same SQL.
    llm_temperature: float = 0.0

    #: Context window to ask the server for. The schema description of a wide
    #: file is the largest thing we send, and silently truncating it would
    #: produce SQL referencing columns the model never saw.
    llm_context_tokens: int = 8192

    #: How long to wait for a plan before giving up on the model.
    llm_timeout_seconds: float = 120.0

    # --- Running the generated query --------------------------------------

    #: Most rows returned to a caller. A question that matches a million rows
    #: is a question that was misunderstood; truncating says so honestly rather
    #: than streaming a million rows into a browser.
    max_result_rows: int = 1000

    #: How long a single query may run before it is cancelled. A ceiling on what
    #: one careless question can cost everyone else.
    query_timeout_seconds: float = 30.0

    #: How long to wait for a cancelled query to actually stop before giving up
    #: on its thread. Only reached if DuckDB ignores an interrupt.
    query_cancel_grace_seconds: float = 5.0

    # --- Background jobs ---------------------------------------------------

    #: How many jobs may run at once. Bounded on purpose: unbounded concurrency
    #: against one DuckDB file moves the queue somewhere we cannot see it.
    job_workers: int = 4

    # --- HTTP -------------------------------------------------------------

    #: Where the API listens. Only used by the launch scripts.
    host: str = "127.0.0.1"
    port: int = 8000

    @property
    def database_file(self) -> Path:
        return self.data_dir / "warehouse.duckdb"

    @property
    def upload_dir(self) -> Path:
        return self.data_dir / "uploads"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Settings are read once per process and cached.

    Cached rather than imported as a module-level singleton so tests can call
    ``get_settings.cache_clear()`` after pointing the environment somewhere else.
    """
    return Settings()
