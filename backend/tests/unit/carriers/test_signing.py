import hashlib
import hmac
from datetime import UTC, datetime, timedelta

import pytest

from veranico.modules.carriers.domain.signing import Verification, sign, verify

SECRET = "unit-test-signing-key"
TIMESTAMP = 1_794_000_000
BODY = b'{"event_id":"0193-test","data":{"premium":{"amount_cents":123456}}}'
TOLERANCE = 300
SENT_AT = datetime.fromtimestamp(TIMESTAMP, tz=UTC)


def _by_hand(secret: str, timestamp: int, body: bytes) -> str:
    message = str(timestamp).encode("ascii") + b"." + body
    return "v1=" + hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


def _verify(
    *,
    secret: str = SECRET,
    timestamp_header: str | None = str(TIMESTAMP),
    signature_header: str | None = None,
    body: bytes = BODY,
    now: datetime = SENT_AT,
) -> Verification:
    if signature_header is None:
        signature_header = sign(SECRET, TIMESTAMP, BODY)
    return verify(secret, timestamp_header, signature_header, body, now, TOLERANCE)


@pytest.mark.req("R-7-1")
def test_signature_is_hmac_sha256_over_timestamp_dot_body() -> None:
    signature = sign(SECRET, TIMESTAMP, BODY)

    assert signature == _by_hand(SECRET, TIMESTAMP, BODY)
    assert signature.startswith("v1=")
    assert len(signature) == len("v1=") + 64


@pytest.mark.req("R-7-1")
def test_signature_covers_the_raw_bytes_not_a_text_decoding() -> None:
    body = b"\xff\x00 not utf-8"

    assert sign(SECRET, TIMESTAMP, body) == _by_hand(SECRET, TIMESTAMP, body)


@pytest.mark.req("R-7-7")
def test_correctly_signed_request_verifies() -> None:
    assert _verify() is Verification.OK


@pytest.mark.req("R-7-7")
def test_one_changed_body_byte_is_a_bad_signature() -> None:
    tampered = BODY.replace(b"123456", b"123457")

    assert _verify(body=tampered) is Verification.BAD_SIGNATURE


@pytest.mark.req("R-7-7")
def test_changed_timestamp_is_a_bad_signature() -> None:
    assert _verify(timestamp_header=str(TIMESTAMP + 1)) is Verification.BAD_SIGNATURE


@pytest.mark.req("R-7-7")
def test_another_secret_is_a_bad_signature() -> None:
    assert _verify(secret="another-signing-key") is Verification.BAD_SIGNATURE


@pytest.mark.req("R-7-7")
@pytest.mark.parametrize(
    ("timestamp_header", "signature_header"),
    [
        (None, sign(SECRET, TIMESTAMP, BODY)),
        (str(TIMESTAMP), None),
        (None, None),
        ("", sign(SECRET, TIMESTAMP, BODY)),
        (str(TIMESTAMP), ""),
    ],
)
def test_missing_header_is_a_bad_signature(
    timestamp_header: str | None, signature_header: str | None
) -> None:
    outcome = verify(SECRET, timestamp_header, signature_header, BODY, SENT_AT, TOLERANCE)

    assert outcome is Verification.BAD_SIGNATURE


@pytest.mark.req("R-7-7")
@pytest.mark.parametrize(
    "timestamp_header",
    [
        "yesterday",
        "1794000000.0",
        "-1794000000",
        "+1794000000",
        " 1794000000",
        "١٧٩٤",  # Arabic-Indic digits: `str.isdigit` alone accepts them
    ],
)
def test_malformed_timestamp_is_a_bad_signature(timestamp_header: str) -> None:
    signature = _by_hand(SECRET, TIMESTAMP, BODY)

    outcome = verify(SECRET, timestamp_header, signature, BODY, SENT_AT, TOLERANCE)

    assert outcome is Verification.BAD_SIGNATURE


@pytest.mark.req("R-7-7")
def test_signature_without_the_version_prefix_is_a_bad_signature() -> None:
    bare_hex = sign(SECRET, TIMESTAMP, BODY).removeprefix("v1=")

    assert _verify(signature_header=bare_hex) is Verification.BAD_SIGNATURE


@pytest.mark.req("R-7-7")
@pytest.mark.parametrize("signature_header", ["v1=", "v1=zz", "v2=" + "0" * 64, "v1=é"])
def test_malformed_signature_is_a_bad_signature(signature_header: str) -> None:
    assert _verify(signature_header=signature_header) is Verification.BAD_SIGNATURE


@pytest.mark.req("R-7-8")
def test_request_exactly_at_the_tolerance_verifies() -> None:
    assert _verify(now=SENT_AT + timedelta(seconds=300)) is Verification.OK


@pytest.mark.req("R-7-8")
def test_request_one_second_past_the_tolerance_is_stale() -> None:
    assert _verify(now=SENT_AT + timedelta(seconds=301)) is Verification.STALE


@pytest.mark.req("R-7-8")
def test_stale_request_with_a_bad_signature_is_a_bad_signature_not_stale() -> None:
    outcome = _verify(secret="another-signing-key", now=SENT_AT + timedelta(seconds=301))

    assert outcome is Verification.BAD_SIGNATURE
