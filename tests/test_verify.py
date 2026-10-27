import pytest

from calendly_pipeline.verify import (
    SignatureError,
    build_header,
    compute_signature,
    parse_header,
    verify,
)

KEY = "test-signing-key"
BODY = b'{"event":"invitee.created","payload":{}}'


def test_round_trip():
    header = build_header(KEY, BODY, timestamp=1_700_000_000)
    parsed = verify(header, BODY, KEY, tolerance_seconds=300, now=1_700_000_010)
    assert parsed.timestamp == 1_700_000_000
    assert parsed.signature == compute_signature(KEY, 1_700_000_000, BODY)


def test_parse_header_tolerates_spaces_and_order():
    parsed = parse_header(" v1=abc , t=42 ")
    assert parsed.timestamp == 42 and parsed.signature == "abc"


@pytest.mark.parametrize("header", [None, "", "t=1", "v1=abc", "t=notanumber,v1=abc"])
def test_malformed_headers(header):
    with pytest.raises(SignatureError):
        verify(header, BODY, KEY, now=1)


def test_wrong_key_rejected():
    header = build_header("other-key", BODY, timestamp=1_700_000_000)
    with pytest.raises(SignatureError, match="mismatch"):
        verify(header, BODY, KEY, now=1_700_000_000)


def test_tampered_body_rejected():
    header = build_header(KEY, BODY, timestamp=1_700_000_000)
    with pytest.raises(SignatureError, match="mismatch"):
        verify(header, BODY + b" ", KEY, now=1_700_000_000)


def test_stale_timestamp_rejected():
    header = build_header(KEY, BODY, timestamp=1_700_000_000)
    with pytest.raises(SignatureError, match="tolerance"):
        verify(header, BODY, KEY, tolerance_seconds=300, now=1_700_000_301)


def test_missing_key_rejected():
    header = build_header(KEY, BODY, timestamp=1_700_000_000)
    with pytest.raises(SignatureError, match="not configured"):
        verify(header, BODY, "", now=1_700_000_000)
