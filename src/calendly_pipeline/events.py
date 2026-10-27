"""Parsing of Calendly webhook events and landing-path construction."""

import json
from dataclasses import dataclass
from datetime import UTC, datetime


class EventError(ValueError):
    """Raised when the body is not a Calendly webhook event that this pipeline handles."""


@dataclass(frozen=True)
class WebhookEvent:
    event_name: str  # invitee.created or invitee.canceled
    created_at: datetime  # when Calendly emitted the event (UTC)
    invitee_uuid: str  # last segment of payload.uri
    invitee_uri: str
    scheduled_event_uri: str
    event_type_uri: str
    raw: dict

    @property
    def landing_name(self) -> str:
        return f"{self.event_name}_{self.invitee_uuid}.json"

    def landing_path(self, prefix: str) -> str:
        day = self.created_at.astimezone(UTC)
        return f"{prefix}/{day:%Y}/{day:%m}/{day:%d}/{self.landing_name}"


def _parse_timestamp(value: str) -> datetime:
    # Calendly uses RFC 3339 with a trailing Z and microseconds, e.g. 2025-07-09T06:04:34.000000Z
    text = value.replace("Z", "+00:00")
    return datetime.fromisoformat(text).astimezone(UTC)


def parse_event(raw_body: bytes, subscribed_events: tuple[str, ...]) -> WebhookEvent:
    try:
        body = json.loads(raw_body)
    except (ValueError, UnicodeDecodeError) as exc:
        raise EventError("body is not valid JSON") from exc
    if not isinstance(body, dict):
        raise EventError("body is not a JSON object")

    event_name = body.get("event")
    if event_name not in subscribed_events:
        raise EventError(f"unsupported event {event_name!r}")

    payload = body.get("payload")
    if not isinstance(payload, dict):
        raise EventError("payload missing")
    invitee_uri = payload.get("uri") or ""
    if "/invitees/" not in invitee_uri:
        raise EventError("payload.uri is not an invitee URI")
    scheduled = payload.get("scheduled_event") or {}
    created_at_text = body.get("created_at") or payload.get("created_at")
    if not created_at_text:
        raise EventError("created_at missing")
    try:
        created_at = _parse_timestamp(created_at_text)
    except ValueError as exc:
        raise EventError("created_at is not a timestamp") from exc

    return WebhookEvent(
        event_name=event_name,
        created_at=created_at,
        invitee_uuid=invitee_uri.rstrip("/").rsplit("/", 1)[-1],
        invitee_uri=invitee_uri,
        scheduled_event_uri=scheduled.get("uri") or payload.get("event") or "",
        event_type_uri=scheduled.get("event_type") or "",
        raw=body,
    )


def envelope(event: WebhookEvent, received_at: datetime, signature_verified: bool) -> dict:
    """The document written to the landing zone: the raw event plus receipt metadata."""
    return {
        "received_at_utc": received_at.astimezone(UTC).isoformat(timespec="microseconds"),
        "signature_verified": signature_verified,
        "event_name": event.event_name,
        "invitee_uuid": event.invitee_uuid,
        "event_type_uri": event.event_type_uri,
        "body": event.raw,
    }
