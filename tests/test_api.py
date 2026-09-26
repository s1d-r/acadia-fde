"""Tests for the HTTP layer.

Two things are being checked. That the async contract holds: work is accepted,
an id comes back, and polling eventually yields a result. And that every failure
leaves the building as a structured error with a sensible status and no
traceback.

The model is scripted throughout, so these tests never touch a network.
"""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from insights import answers
from insights.api import create_app
from insights.llm.fake import FakeLLMClient

from .conftest import FIXTURES


@pytest.fixture
def client():
    with TestClient(create_app()) as test_client:
        yield test_client


@pytest.fixture
def scripted(monkeypatch):
    """Point the answer path at a scripted model."""

    def use(fake: FakeLLMClient):
        monkeypatch.setattr(answers, "build_client", lambda: fake)
        return fake

    return use


def wait_for(client: TestClient, job_id: str, timeout: float = 30.0) -> dict:
    """Poll a job the way a caller would, until it finishes."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("succeeded", "failed"):
            return job
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} did not finish within {timeout}s")


def upload(client: TestClient, filename: str) -> dict:
    with (FIXTURES / filename).open("rb") as handle:
        response = client.post(
            "/api/datasets", files={"file": (filename, handle, "text/csv")}
        )
    assert response.status_code == 202, response.text
    return wait_for(client, response.json()["job_id"])


# --- the service ------------------------------------------------------------


def test_health_does_not_need_anything_else_to_be_working(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_the_ui_is_served_at_the_root(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "<title>Insights</title>" in response.text


# --- ingestion --------------------------------------------------------------


def test_uploading_a_csv_returns_a_job_immediately(client):
    with (FIXTURES / "library_loans.csv").open("rb") as handle:
        response = client.post(
            "/api/datasets", files={"file": ("library_loans.csv", handle, "text/csv")}
        )

    assert response.status_code == 202
    body = response.json()
    assert body["status"] in ("queued", "running")
    assert body["job_id"]


def test_polling_an_upload_yields_the_profile(client):
    job = upload(client, "library_loans.csv")

    assert job["status"] == "succeeded"
    assert job["result"]["row_count"] == 300
    assert job["result"]["column_count"] == 9
    assert job["dataset_id"] == job["result"]["dataset_id"]


def test_an_ingested_dataset_is_listed(client):
    job = upload(client, "library_loans.csv")
    listed = client.get("/api/datasets").json()["datasets"]

    assert [d["dataset_id"] for d in listed] == [job["dataset_id"]]


def test_the_profile_can_be_fetched(client):
    job = upload(client, "library_loans.csv")
    profile = client.get(f"/api/datasets/{job['dataset_id']}").json()

    assert [c["name"] for c in profile["columns"]][:2] == [
        "Loan Reference",
        "Borrowed On",
    ]


def test_the_schema_context_is_visible(client):
    """What the model was told is the first thing to look at when it is wrong."""
    job = upload(client, "library_loans.csv")
    body = client.get(f"/api/datasets/{job['dataset_id']}/context").json()

    assert '"Branch Library"' in body["prompt_text"]
    assert body["context"]["column_count"] == 9


def test_a_file_that_cannot_be_read_fails_the_job_not_the_request(client):
    """The upload was accepted, so the request succeeded. The work did not."""
    job = upload(client, "header_only.csv")

    assert job["status"] == "failed"
    assert job["error"]["code"] == "ingestion_failed"


def test_a_file_with_the_wrong_extension_is_refused_at_the_boundary(client):
    response = client.post(
        "/api/datasets", files={"file": ("notes.pdf", b"%PDF-1.4", "application/pdf")}
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_file"


def test_an_empty_upload_is_refused(client):
    response = client.post(
        "/api/datasets", files={"file": ("empty.csv", b"", "text/csv")}
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_file"


def test_an_upload_over_the_size_limit_is_refused(client, monkeypatch):
    from insights.config import get_settings

    monkeypatch.setenv("INSIGHTS_MAX_CSV_BYTES", "32")
    get_settings.cache_clear()

    response = client.post(
        "/api/datasets",
        files={"file": ("big.csv", b"a,b\n" + b"1,2\n" * 100, "text/csv")},
    )

    assert response.status_code == 400
    assert response.json()["error"]["details"]["limit_bytes"] == 32


# --- questions --------------------------------------------------------------


def test_asking_a_question_returns_a_job_and_then_an_answer(client, scripted):
    job = upload(client, "library_loans.csv")
    dataset_id = job["dataset_id"]
    table = job["result"]["table_name"]
    scripted(
        FakeLLMClient.answering(
            f'SELECT "Branch Library", count(*) AS n FROM "{table}" GROUP BY 1 ORDER BY 1',
            reason="Counts loans per branch.",
        )
    )

    accepted = client.post(
        f"/api/datasets/{dataset_id}/questions", json={"question": "Loans per branch?"}
    )
    assert accepted.status_code == 202

    answer = wait_for(client, accepted.json()["job_id"])["result"]
    assert answer["outcome"] == "query"
    assert answer["result"]["columns"] == ["Branch Library", "n"]
    assert answer["result"]["row_count"] == 4
    assert answer["sql"].startswith("SELECT")


def test_a_refusal_is_a_successful_job(client, scripted):
    """A refusal is a correct answer. It must not look like a failure."""
    job = upload(client, "library_loans.csv")
    scripted(FakeLLMClient.refusing("There is no column recording a supplier."))

    accepted = client.post(
        f"/api/datasets/{job['dataset_id']}/questions",
        json={"question": "Which supplier was slowest?"},
    )
    finished = wait_for(client, accepted.json()["job_id"])

    assert finished["status"] == "succeeded"
    assert finished["result"]["outcome"] == "refusal"
    assert finished["result"]["sql"] is None
    assert finished["error"] is None


def test_sql_the_validator_rejects_fails_the_job_with_its_reason(client, scripted):
    job = upload(client, "library_loans.csv")
    scripted(FakeLLMClient.answering('SELECT * FROM read_csv(\'/etc/passwd\')'))

    accepted = client.post(
        f"/api/datasets/{job['dataset_id']}/questions", json={"question": "anything"}
    )
    finished = wait_for(client, accepted.json()["job_id"])

    assert finished["status"] == "failed"
    assert finished["error"]["code"] == "unsafe_query"


def test_asking_about_a_dataset_that_does_not_exist_is_a_404(client):
    response = client.post(
        "/api/datasets/nope/questions", json={"question": "anything"}
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "dataset_not_found"


def test_a_bad_dataset_id_is_rejected_before_a_job_is_created(client):
    """A 404 now beats a job that fails a moment later."""
    before = client.get("/api/datasets").json()
    client.post("/api/datasets/nope/questions", json={"question": "anything"})
    after = client.get("/api/datasets").json()

    assert before == after


def test_an_empty_question_is_a_validation_error(client):
    job = upload(client, "library_loans.csv")
    response = client.post(
        f"/api/datasets/{job['dataset_id']}/questions", json={"question": ""}
    )

    assert response.status_code == 422
    body = response.json()["error"]
    assert body["code"] == "invalid_request"
    assert body["details"]["fields"][0]["field"] == "question"


def test_a_missing_question_field_is_a_validation_error(client):
    job = upload(client, "library_loans.csv")
    response = client.post(f"/api/datasets/{job['dataset_id']}/questions", json={})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"


# --- jobs -------------------------------------------------------------------


def test_an_unknown_job_is_a_404(client):
    response = client.get("/api/jobs/does-not-exist")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "job_not_found"


# --- the error contract -----------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("get", "/api/datasets/nope", None),
        ("get", "/api/jobs/nope", None),
        ("post", "/api/datasets/nope/questions", {"question": "x"}),
    ],
)
def test_every_error_has_the_same_shape(client, method, path, payload):
    response = getattr(client, method)(path, json=payload) if payload else getattr(
        client, method
    )(path)

    body = response.json()
    assert set(body) == {"error"}
    assert set(body["error"]) == {"code", "message", "details"}


def test_errors_never_carry_a_traceback(client):
    response = client.get("/api/datasets/nope")

    assert "Traceback" not in response.text
    assert "File \"" not in response.text
