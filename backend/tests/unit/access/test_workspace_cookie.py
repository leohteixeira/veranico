import secrets
import string
from datetime import UTC, datetime, timedelta

import pytest

from veranico.modules.access.domain import workspace_cookie

NOW = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)
EXPIRES = NOW + timedelta(days=14)

pytestmark = pytest.mark.req("R-10.1-1")


@pytest.fixture
def secret() -> str:
    return secrets.token_hex(16)


def _flip(character: str) -> str:
    return "0" if character != "0" else "1"


def _with_changed_character(value: str, part: int) -> str:
    parts = value.split(".")
    parts[part] = _flip(parts[part][0]) + parts[part][1:]
    return ".".join(parts)


def test_signed_value_verifies_to_its_workspace_and_expiry(secret: str) -> None:
    workspace_id = workspace_cookie.new_workspace_id()

    value = workspace_cookie.sign(workspace_id, EXPIRES, secret)

    assert value.startswith(f"v1.{workspace_id}.{int(EXPIRES.timestamp())}.")
    assert workspace_cookie.verify(value, secret, NOW) == (workspace_id, EXPIRES)


@pytest.mark.parametrize("part", [1, 2, 3], ids=["workspace id", "expiry", "signature"])
def test_one_changed_character_fails_verification(secret: str, part: int) -> None:
    value = workspace_cookie.sign(workspace_cookie.new_workspace_id(), EXPIRES, secret)

    tampered = _with_changed_character(value, part)

    assert tampered != value
    assert workspace_cookie.verify(tampered, secret, NOW) is None


def test_a_later_expiry_cannot_be_written_into_the_value(secret: str) -> None:
    value = workspace_cookie.sign(workspace_cookie.new_workspace_id(), EXPIRES, secret)
    version, workspace_id, _, signature = value.split(".")
    later = int((EXPIRES + timedelta(days=365)).timestamp())

    extended = f"{version}.{workspace_id}.{later}.{signature}"

    assert workspace_cookie.verify(extended, secret, NOW) is None


def test_value_signed_with_another_secret_fails(secret: str) -> None:
    value = workspace_cookie.sign(
        workspace_cookie.new_workspace_id(), EXPIRES, secrets.token_hex(16)
    )

    assert workspace_cookie.verify(value, secret, NOW) is None


def test_missing_part_fails(secret: str) -> None:
    value = workspace_cookie.sign(workspace_cookie.new_workspace_id(), EXPIRES, secret)
    version, workspace_id, expires, signature = value.split(".")

    assert workspace_cookie.verify(f"{version}.{workspace_id}.{signature}", secret, NOW) is None
    assert workspace_cookie.verify(f"{version}.{workspace_id}.{expires}", secret, NOW) is None
    assert workspace_cookie.verify(f"{value}.extra", secret, NOW) is None


def test_unknown_version_prefix_fails(secret: str) -> None:
    value = workspace_cookie.sign(workspace_cookie.new_workspace_id(), EXPIRES, secret)

    assert workspace_cookie.verify("v2" + value[2:], secret, NOW) is None


def test_expiry_in_the_past_fails(secret: str) -> None:
    value = workspace_cookie.sign(workspace_cookie.new_workspace_id(), EXPIRES, secret)

    assert workspace_cookie.verify(value, secret, EXPIRES - timedelta(seconds=1)) is not None
    assert workspace_cookie.verify(value, secret, EXPIRES) is None
    assert workspace_cookie.verify(value, secret, EXPIRES + timedelta(days=1)) is None


@pytest.mark.parametrize("value", ["", "v1", "...", "v1...", "not a cookie", "v1.é.1.é"])
def test_malformed_value_fails(secret: str, value: str) -> None:
    assert workspace_cookie.verify(value, secret, NOW) is None


def test_new_workspace_ids_differ_and_are_32_hexadecimal_characters() -> None:
    first, second = workspace_cookie.new_workspace_id(), workspace_cookie.new_workspace_id()

    assert first != second
    for workspace_id in (first, second):
        assert len(workspace_id) == 32
        assert set(workspace_id) <= set(string.hexdigits.lower())
