import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from calendly_pipeline.config import SUBSCRIBED_EVENTS
from calendly_pipeline.events import EventError, envelope, parse_event

FIXTURE = Path(__file__).parent / "fixtures" / "sample_invitee_created.json"


def sample_bytes(**overrides) -> bytes:
    body = json.loads(FIXTURE.read_text(encoding="utf-8"))
    body.update(overrides)
    return json.dumps(body).encode("utf-8")


def test_parse_sample_event():
    event = parse_event(sample_bytes(), SUBSCRIBED_EVENTS)
    assert event.event_name == "invitee.created"
    assert event.invitee_uuid == "22a0f2d6-1bde-4fc1-95c1-d969df1da21d"
    assert event.event_type_uri.endswith("/event_types/d639ecd3-8718-4068-955a-436b10d72c78")
    assert event.scheduled_event_uri.endswith(
        "/scheduled_events/1ac9e88e-eae3-4e4b-b979-d770cff02d72"
    )
    assert event.created_at == datetime(2025, 7, 9, 6, 4, 34, tzinfo=UTC)


def test_landing_path_uses_event_date_and_name():
    event = parse_event(sample_bytes(), SUBSCRIBED_EVENTS)
    assert event.landing_path("calendly/landing") == (
        "calendly/landing/2025/07/09/invitee.created_22a0f2d6-1bde-4fc1-95c1-d969df1da21d.json"
    )


def test_canceled_event_accepted_with_distinct_name():
    event = parse_event(sample_bytes(event="invitee.canceled"), SUBSCRIBED_EVENTS)
    assert event.landing_name == "invitee.canceled_22a0f2d6-1bde-4fc1-95c1-d969df1da21d.json"


@pytest.mark.parametrize(
    "event_name", ["routing_form_submission.created", "invitee_no_show.created", None]
)
def test_other_events_rejected(event_name):
    with pytest.raises(EventError, match="unsupported"):
        parse_event(sample_bytes(event=event_name), SUBSCRIBED_EVENTS)


def test_invalid_json_rejected():
    with pytest.raises(EventError, match="valid JSON"):
        parse_event(b"not json", SUBSCRIBED_EVENTS)


def test_missing_payload_rejected():
    with pytest.raises(EventError, match="payload"):
        parse_event(b'{"event": "invitee.created"}', SUBSCRIBED_EVENTS)


def test_envelope_carries_receipt_metadata():
    event = parse_event(sample_bytes(), SUBSCRIBED_EVENTS)
    received = datetime(2026, 10, 27, 14, 0, tzinfo=UTC)
    doc = envelope(event, received, signature_verified=True)
    assert doc["received_at_utc"].startswith("2026-10-27T14:00:00")
    assert doc["signature_verified"] is True
    assert doc["body"]["payload"]["uri"] == event.invitee_uri
