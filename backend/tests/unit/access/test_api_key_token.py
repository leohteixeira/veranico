import pytest

from veranico.modules.access.domain import api_key_token

pytestmark = pytest.mark.req("R-10.2-1")


def test_minted_bearer_parses_into_key_id_and_secret() -> None:
    key_id, secret = api_key_token.mint()

    bearer = api_key_token.format_bearer(key_id, secret)

    assert bearer.startswith("vrk_")
    assert api_key_token.parse_bearer(bearer) == (key_id, secret)


def test_secret_with_underscores_parses_whole() -> None:
    bearer = api_key_token.format_bearer("abc123", "se_cr_et_")

    assert api_key_token.parse_bearer(bearer) == ("abc123", "se_cr_et_")


def test_minted_secret_carries_256_random_bits() -> None:
    _, secret = api_key_token.mint()

    assert len(secret) >= 43  # 32 bytes in unpadded URL-safe base64


def test_stored_hash_matches_only_that_secret() -> None:
    _, secret = api_key_token.mint()
    _, other = api_key_token.mint()

    stored = api_key_token.hash_secret(secret)

    assert secret not in stored
    assert api_key_token.secret_matches(secret, stored)
    assert not api_key_token.secret_matches(other, stored)
    assert not api_key_token.secret_matches(secret + "x", stored)
    assert not api_key_token.secret_matches("", stored)


@pytest.mark.parametrize(
    "bearer",
    [
        "",
        "abc123_secret",  # no prefix
        "key_abc123_secret",  # another prefix
        "vrk_abc123",  # no secret
        "vrk_abc123_",  # empty secret
        "vrk__secret",  # empty key id
        "vrk",
        "vrk_",
    ],
)
def test_malformed_bearer_does_not_parse(bearer: str) -> None:
    assert api_key_token.parse_bearer(bearer) is None


def test_two_minted_keys_differ() -> None:
    first, second = api_key_token.mint(), api_key_token.mint()

    assert first[0] != second[0]
    assert first[1] != second[1]
