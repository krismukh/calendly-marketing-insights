"""Calendly webhook signature verification.

Calendly sends the header

    Calendly-Webhook-Signature: t=<unix seconds>,v1=<hex HMAC-SHA256>

where the signature is computed over the string "<t>.<raw request body>" with the
signing key returned when the webhook subscription was created.
"""

import hashlib
import hmac
import time
from dataclasses import dataclass

HEADER_NAME = "Calendly-Webhook-Signature"


class SignatureError(ValueError):
    """Raised when the signature header is missing, malformed, stale, or wrong."""


@dataclass(frozen=True)
class ParsedSignature:
    timestamp: int
    signature: str


def parse_header(header_value: str | None) -> ParsedSignature:
    if not header_value:
        raise SignatureError("missing signature header")
    parts: dict[str, str] = {}
    for item in header_value.split(","):
        key, sep, value = item.strip().partition("=")
        if sep:
            parts[key.strip()] = value.strip()
    if "t" not in parts or "v1" not in parts:
        raise SignatureError("malformed signature header")
    try:
        timestamp = int(parts["t"])
    except ValueError as exc:
        raise SignatureError("malformed timestamp") from exc
    return ParsedSignature(timestamp=timestamp, signature=parts["v1"].lower())


def compute_signature(signing_key: str, timestamp: int, raw_body: bytes) -> str:
    message = f"{timestamp}.".encode() + raw_body
    return hmac.new(signing_key.encode("utf-8"), message, hashlib.sha256).hexdigest()


def verify(
    header_value: str | None,
    raw_body: bytes,
    signing_key: str,
    tolerance_seconds: int = 300,
    now: float | None = None,
) -> ParsedSignature:
    """Return the parsed signature when valid; raise SignatureError otherwise."""
    if not signing_key:
        raise SignatureError("signing key not configured")
    parsed = parse_header(header_value)
    current = time.time() if now is None else now
    if abs(current - parsed.timestamp) > tolerance_seconds:
        raise SignatureError("signature timestamp outside tolerance")
    expected = compute_signature(signing_key, parsed.timestamp, raw_body)
    if not hmac.compare_digest(expected, parsed.signature):
        raise SignatureError("signature mismatch")
    return parsed


def build_header(signing_key: str, raw_body: bytes, timestamp: int | None = None) -> str:
    """Produce a header value for a body; used by the test-event script and the tests."""
    ts = int(time.time()) if timestamp is None else timestamp
    return f"t={ts},v1={compute_signature(signing_key, ts, raw_body)}"
