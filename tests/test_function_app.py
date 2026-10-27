"""Tests for the HTTP receiver logic with an in-memory landing zone."""

import json
from pathlib import Path

import azure.functions as func
import pytest

import function_app
from calendly_pipeline.landing import MemoryLanding
from calendly_pipeline.verify import HEADER_NAME, build_header

FIXTURE = Path(__file__).parent / "fixtures" / "sample_invitee_created.json"
KEY = "unit-test-signing-key"


def make_request(body: bytes, headers: dict | None = None) -> func.HttpRequest:
    return func.HttpRequest(method="POST", url="/api/calendly", body=body, headers=headers or {})


@pytest.fixture
def landing():
    mem = MemoryLanding()
    function_app.set_landing(mem)
    yield mem
    function_app.set_landing(None)


@pytest.fixture
def sample_body() -> bytes:
    return FIXTURE.read_bytes()


def test_lands_sample_event_without_verification(monkeypatch, landing, sample_body):
    monkeypatch.setenv("VERIFY_SIGNATURE", "false")
    response = function_app.handle_calendly(make_request(sample_body), landing)
    assert response.status_code == 200
    body = json.loads(response.get_body())
    assert body["status"] == "landed"
    assert (
        body["path"]
        == "calendly/landing/2025/07/09/invitee.created_22a0f2d6-1bde-4fc1-95c1-d969df1da21d.json"
    )
    stored = json.loads(landing.blobs[body["path"]])
    assert stored["signature_verified"] is False
    assert stored["body"]["event"] == "invitee.created"


def test_repeated_delivery_overwrites_same_path(monkeypatch, landing, sample_body):
    monkeypatch.setenv("VERIFY_SIGNATURE", "false")
    function_app.handle_calendly(make_request(sample_body), landing)
    function_app.handle_calendly(make_request(sample_body), landing)
    assert len(landing.blobs) == 1


def test_verification_rejects_missing_signature(monkeypatch, landing, sample_body):
    monkeypatch.setenv("VERIFY_SIGNATURE", "true")
    monkeypatch.setenv("CALENDLY_SIGNING_KEY", KEY)
    response = function_app.handle_calendly(make_request(sample_body), landing)
    assert response.status_code == 401
    assert landing.blobs == {}


def test_verification_accepts_signed_request(monkeypatch, landing, sample_body):
    monkeypatch.setenv("VERIFY_SIGNATURE", "true")
    monkeypatch.setenv("CALENDLY_SIGNING_KEY", KEY)
    headers = {HEADER_NAME: build_header(KEY, sample_body)}
    response = function_app.handle_calendly(make_request(sample_body, headers), landing)
    assert response.status_code == 200
    stored = json.loads(next(iter(landing.blobs.values())))
    assert stored["signature_verified"] is True


def test_unsupported_event_is_acknowledged_and_not_landed(monkeypatch, landing, sample_body):
    monkeypatch.setenv("VERIFY_SIGNATURE", "false")
    body = json.loads(sample_body)
    body["event"] = "routing_form_submission.created"
    response = function_app.handle_calendly(make_request(json.dumps(body).encode()), landing)
    assert response.status_code == 200
    assert json.loads(response.get_body())["status"] == "skipped"
    assert landing.blobs == {}


def test_invalid_json_is_acknowledged(monkeypatch, landing):
    monkeypatch.setenv("VERIFY_SIGNATURE", "false")
    response = function_app.handle_calendly(make_request(b"{not json"), landing)
    assert response.status_code == 200
    assert landing.blobs == {}


def test_storage_failure_returns_500(monkeypatch, sample_body):
    monkeypatch.setenv("VERIFY_SIGNATURE", "false")

    class FailingLanding(MemoryLanding):
        def write_json(self, path, document, metadata=None):
            raise RuntimeError("storage down")

    response = function_app.handle_calendly(make_request(sample_body), FailingLanding())
    assert response.status_code == 500


def test_health_reports_configuration(monkeypatch):
    monkeypatch.setenv("STORAGE_ACCOUNT_URL", "https://stcalendlykcm.blob.core.windows.net")
    monkeypatch.setenv("CALENDLY_SIGNING_KEY", "pending-from-program")
    request = func.HttpRequest(method="GET", url="/api/health", body=b"")
    response = function_app.health.build().get_user_function()(request)
    body = json.loads(response.get_body())
    assert body["status"] == "ok"
    assert body["storage_configured"] is True
    assert body["signing_key_present"] is False
    assert body["subscribed_events"] == ["invitee.created", "invitee.canceled"]
