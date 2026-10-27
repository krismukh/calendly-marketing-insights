"""Discovery, download, validation, and landing of the daily marketing spend files.

The public bucket publishes spend_data_YYYY-MM-DD.json at 06:00 AM Eastern for the
previous day, each holding up to 30 days of records, and file_index.json listing the
files currently available (a rolling window of 30 names, decision 18). Files older than
the window cannot be re-fetched, so every landed file is kept.
"""

import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import requests

from .landing import Landing

EASTERN = ZoneInfo("America/New_York")
FILE_PATTERN = re.compile(r"^spend_data_(\d{4}-\d{2}-\d{2})\.json$")
CHANNELS = {"facebook_paid_ads", "youtube_paid_ads", "tiktok_paid_ads"}
TIMEOUT = 30


class SpendFileError(ValueError):
    """Raised when a downloaded file does not have the expected shape."""


@dataclass
class FetchSummary:
    index_files: int = 0
    already_landed: int = 0
    landed: list[str] = field(default_factory=list)
    quarantined: list[str] = field(default_factory=list)
    expected_latest: str = ""
    latest_available: bool = False
    errors: list[str] = field(default_factory=list)


def file_names_from_index(index: object) -> list[str]:
    """Accept {"files": [...]} (the observed format) or a bare list of names."""
    if isinstance(index, dict):
        for key in ("files", "file_names", "filenames", "keys", "objects"):
            if key in index:
                return file_names_from_index(index[key])
        return []
    names: list[str] = []
    for item in index:
        name = (
            item
            if isinstance(item, str)
            else next(
                (
                    str(item[k])
                    for k in ("file_name", "filename", "name", "key", "file")
                    if isinstance(item, dict) and k in item
                ),
                None,
            )
        )
        if name:
            names.append(name.rsplit("/", 1)[-1])
    return sorted(n for n in names if FILE_PATTERN.match(n))


def file_date(name: str) -> date:
    match = FILE_PATTERN.match(name)
    if not match:
        raise ValueError(f"not a spend file name: {name}")
    return date.fromisoformat(match.group(1))


def expected_latest_name(now: datetime | None = None) -> str:
    """The Day-1 file name in Eastern time."""
    current = now.astimezone(EASTERN) if now else datetime.now(EASTERN)
    return f"spend_data_{(current.date() - timedelta(days=1)).isoformat()}.json"


def validate_records(data: object) -> list[dict]:
    if not isinstance(data, list) or not data:
        raise SpendFileError("file is not a non-empty JSON array")
    seen: set[tuple[str, str]] = set()
    for i, record in enumerate(data):
        if not isinstance(record, dict) or set(record) != {"date", "channel", "spend"}:
            raise SpendFileError(f"record {i} does not have exactly date, channel, spend")
        try:
            date.fromisoformat(record["date"])
        except (TypeError, ValueError) as exc:
            raise SpendFileError(f"record {i} has an invalid date") from exc
        if record["channel"] not in CHANNELS:
            raise SpendFileError(f"record {i} has unknown channel {record['channel']!r}")
        if (
            not isinstance(record["spend"], int | float)
            or isinstance(record["spend"], bool)
            or record["spend"] < 0
        ):
            raise SpendFileError(f"record {i} has an invalid spend")
        key = (record["date"], record["channel"])
        if key in seen:
            raise SpendFileError(f"duplicate date and channel {key}")
        seen.add(key)
    return data


class SpendFetcher:
    def __init__(
        self,
        base_url: str,
        landing: Landing,
        landing_prefix: str,
        quarantine_prefix: str,
        lookback_days: int = 35,
        session: requests.Session | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.landing = landing
        self.landing_prefix = landing_prefix.rstrip("/")
        self.quarantine_prefix = quarantine_prefix.rstrip("/")
        self.lookback_days = lookback_days
        self.session = session or requests.Session()

    def _get(self, name: str) -> bytes:
        response = self.session.get(f"{self.base_url}/{name}", timeout=TIMEOUT)
        response.raise_for_status()
        return response.content

    def run(self, now: datetime | None = None) -> FetchSummary:
        summary = FetchSummary(expected_latest=expected_latest_name(now))
        index = json.loads(self._get("file_index.json"))
        names = file_names_from_index(index)
        summary.index_files = len(names)
        summary.latest_available = summary.expected_latest in names

        cutoff = (
            now.astimezone(EASTERN).date() if now else datetime.now(EASTERN).date()
        ) - timedelta(days=self.lookback_days)
        wanted = [n for n in names if file_date(n) >= cutoff]
        present = self.landing.list_names(self.landing_prefix)

        for name in wanted:
            if name in present:
                summary.already_landed += 1
                continue
            try:
                raw = self._get(name)
            except requests.RequestException as exc:
                summary.errors.append(f"{name}: {exc}")
                continue
            metadata = {
                "source_url": f"{self.base_url}/{name}",
                "file_date": file_date(name).isoformat(),
            }
            try:
                validate_records(json.loads(raw))
            except (ValueError, SpendFileError) as exc:
                self.landing.write_bytes(
                    f"{self.quarantine_prefix}/{name}", raw, {**metadata, "reason": str(exc)[:250]}
                )
                summary.quarantined.append(name)
                continue
            self.landing.write_bytes(f"{self.landing_prefix}/{name}", raw, metadata)
            summary.landed.append(name)
        return summary
