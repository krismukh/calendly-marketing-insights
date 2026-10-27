"""Phase 0 tests: the fixtures extracted from the requirements document are well formed
and carry the elements the pipeline depends on (proposal, Section 3.1 and 3.2)."""

import json
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"

CAMPAIGN_CHANNELS = {"facebook_paid_ads", "youtube_paid_ads", "tiktok_paid_ads"}


def load(name: str):
    with (FIXTURES / name).open(encoding="utf-8") as fh:
        return json.load(fh)


def test_invitee_created_event_shape():
    event = load("sample_invitee_created.json")
    assert event["event"] == "invitee.created"
    payload = event["payload"]
    assert payload["uri"].startswith("https://api.calendly.com/scheduled_events/")
    assert "/invitees/" in payload["uri"]
    scheduled = payload["scheduled_event"]
    assert scheduled["event_type"].startswith("https://api.calendly.com/event_types/")
    assert scheduled["start_time"].endswith("Z")
    assert scheduled["end_time"].endswith("Z")
    assert len(scheduled["event_memberships"]) == 1
    assert scheduled["event_memberships"][0]["user"].startswith("https://api.calendly.com/users/")


def test_invitee_created_tracking_block_present():
    tracking = load("sample_invitee_created.json")["payload"]["tracking"]
    for key in ("utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term"):
        assert key in tracking


def test_spend_file_shape():
    records = load("sample_spend_2025-06-24.json")
    assert isinstance(records, list) and len(records) == 3
    for record in records:
        assert set(record) == {"date", "channel", "spend"}
        assert record["channel"] in CAMPAIGN_CHANNELS
        assert isinstance(record["spend"], (int, float)) and record["spend"] > 0
    assert {r["channel"] for r in records} == CAMPAIGN_CHANNELS
