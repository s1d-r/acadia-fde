"""Request and response shapes for the API.

Separate from the engine's own models on purpose. These describe the wire
contract, and the wire contract should be able to stay still while the internals
move. Where a model is already exactly the right shape, it is reused rather than
copied, because two definitions of the same thing drift.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from ..models.context import SchemaContext
from ..models.job import Job, JobStatus
from ..models.profile import DatasetSummary


class AskRequest(BaseModel):
    """A question about one dataset."""

    question: str = Field(
        min_length=1,
        max_length=1000,
        description="The question, in plain English.",
    )

    model_config = {
        "json_schema_extra": {
            "examples": [{"question": "What are the top 10 products by revenue?"}]
        }
    }


class JobAccepted(BaseModel):
    """What a caller gets when work has been queued.

    Only the id and the status. Anything else would be guessing about a job
    that has not run yet.
    """

    job_id: str
    status: JobStatus


class JobView(Job):
    """A job as returned by the API. Identical to the internal record."""


class DatasetList(BaseModel):
    datasets: list[DatasetSummary]


class SchemaContextView(BaseModel):
    """The planner's view of a dataset, in both forms."""

    context: SchemaContext
    prompt_text: str = Field(
        description="The exact text block the model is given, so a wrong answer "
        "can be traced to what the model actually knew."
    )
