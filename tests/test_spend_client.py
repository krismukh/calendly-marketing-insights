import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
import requests

from calendly_pipeline.landing import MemoryLanding
from calendly_pipeline.spend_client import (
    SpendFetcher,
    SpendFileError,
    expected_latest_name,
    file_date,
    file_names_from_index,
    validate_records,
)

EASTERN = ZoneInfo("America/New_York")
NOW = datetime(2026, 10, 27, 10, 30, tzinfo=EASTERN)


def records_for(day: str, spend: float = 100.0) -> list[dict]:
    return [
        {"date": day, "channel": c, "spend": spend}
        for c in ("facebook_paid_ads", "youtube_paid_ads", "tiktok_paid_ads")
    ]


class FakeResponse:
    def __init__(self, content: bytes, status: int = 200):
        self.content = content
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"status {self.status_code}")


class FakeSession:
    """Serves a dictionary of path -> bytes; counts downloads."""

    def __init__(self, files: dict[str, bytes]):
        self.files = files
        self.requested: list[str] = []

    def get(self, url, timeout=None):
        name = url.rsplit("/", 1)[-1]
        self.requested.append(name)
        if name not in self.files:
            return FakeResponse(b"", 404)
        return FakeResponse(self.files[name])


def test_index_formats():
    names = ["spend_data_2026-10-25.json", "spend_data_2026-10-26.json"]
    assert file_names_from_index({"files": names}) == names
    assert file_names_from_index(names) == names
    assert file_names_from_index([{"name": "x/" + n} for n in names]) == names
    assert file_names_from_index({"files": ["readme.txt", *names]}) == names


def test_file_date_and_expected_latest():
    assert file_date("spend_data_2026-10-26.json").isoformat() == "2026-10-26"
    assert expected_latest_name(NOW) == "spend_data_2026-10-26.json"
    with pytest.raises(ValueError):
        file_date("other.json")


def test_validate_records_accepts_good_file():
    assert len(validate_records(records_for("2026-10-26"))) == 3


@pytest.mark.parametrize(
    "bad",
    [
        [],
        [{"date": "2026-10-26", "channel": "facebook_paid_ads"}],
        [{"date": "26/10/2026", "channel": "facebook_paid_ads", "spend": 1}],
        [{"date": "2026-10-26", "channel": "google_ads", "spend": 1}],
        [{"date": "2026-10-26", "channel": "facebook_paid_ads", "spend": "1"}],
        [{"date": "2026-10-26", "channel": "facebook_paid_ads", "spend": -1}],
        records_for("2026-10-26") + records_for("2026-10-26"),
    ],
)
def test_validate_records_rejects_bad_files(bad):
    with pytest.raises(SpendFileError):
        validate_records(bad)


def make_fetcher(files: dict[str, bytes], landing: MemoryLanding | None = None):
    landing = landing or MemoryLanding()
    session = FakeSession(files)
    fetcher = SpendFetcher(
        "https://example.test/spend", landing, "spend/landing", "spend/quarantine", 35, session
    )
    return fetcher, landing, session


def test_lands_new_files_and_skips_existing():
    files = {
        "file_index.json": json.dumps(
            {"files": ["spend_data_2026-10-25.json", "spend_data_2026-10-26.json"]}
        ).encode(),
        "spend_data_2026-10-25.json": json.dumps(records_for("2026-10-25")).encode(),
        "spend_data_2026-10-26.json": json.dumps(records_for("2026-10-26")).encode(),
    }
    landing = MemoryLanding()
    landing.write_bytes("spend/landing/spend_data_2026-10-25.json", b"[]")
    fetcher, landing, session = make_fetcher(files, landing)

    summary = fetcher.run(NOW)

    assert summary.index_files == 2
    assert summary.already_landed == 1
    assert summary.landed == ["spend_data_2026-10-26.json"]
    assert summary.latest_available is True
    assert "spend_data_2026-10-25.json" not in session.requested
    assert landing.metadata["spend/landing/spend_data_2026-10-26.json"]["file_date"] == "2026-10-26"


def test_latest_missing_is_reported_not_fatal():
    files = {
        "file_index.json": json.dumps({"files": ["spend_data_2026-10-25.json"]}).encode(),
        "spend_data_2026-10-25.json": json.dumps(records_for("2026-10-25")).encode(),
    }
    fetcher, landing, _ = make_fetcher(files)
    summary = fetcher.run(NOW)
    assert summary.latest_available is False
    assert summary.landed == ["spend_data_2026-10-25.json"]


def test_invalid_file_is_quarantined():
    files = {
        "file_index.json": json.dumps({"files": ["spend_data_2026-10-26.json"]}).encode(),
        "spend_data_2026-10-26.json": b'[{"date": "2026-10-26", "channel": "google", "spend": 1}]',
    }
    fetcher, landing, _ = make_fetcher(files)
    summary = fetcher.run(NOW)
    assert summary.quarantined == ["spend_data_2026-10-26.json"]
    assert landing.exists("spend/quarantine/spend_data_2026-10-26.json")
    assert not landing.exists("spend/landing/spend_data_2026-10-26.json")


def test_download_error_is_recorded_and_others_continue():
    files = {
        "file_index.json": json.dumps(
            {"files": ["spend_data_2026-10-25.json", "spend_data_2026-10-26.json"]}
        ).encode(),
        "spend_data_2026-10-26.json": json.dumps(records_for("2026-10-26")).encode(),
    }
    fetcher, _, _ = make_fetcher(files)
    summary = fetcher.run(NOW)
    assert len(summary.errors) == 1 and "2026-10-25" in summary.errors[0]
    assert summary.landed == ["spend_data_2026-10-26.json"]


def test_lookback_limits_downloads():
    old = "spend_data_2026-01-01.json"
    files = {
        "file_index.json": json.dumps({"files": [old, "spend_data_2026-10-26.json"]}).encode(),
        old: json.dumps(records_for("2026-01-01")).encode(),
        "spend_data_2026-10-26.json": json.dumps(records_for("2026-10-26")).encode(),
    }
    fetcher, _, session = make_fetcher(files)
    fetcher.run(NOW)
    assert old not in session.requested
