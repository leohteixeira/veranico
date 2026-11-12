import secrets

import pytest

from veranico.modules.access.domain import visitor

# Documentation ranges (RFC 5737, RFC 3849): not the address of anyone.
ADDRESS = "203.0.113.57"


@pytest.fixture
def salt() -> str:
    return secrets.token_hex(16)


@pytest.mark.req("R-10.3-1")
def test_same_address_and_salt_give_the_same_hash(salt: str) -> None:
    assert visitor.hash_address(ADDRESS, salt) == visitor.hash_address(ADDRESS, salt)
    assert visitor.hash_address(ADDRESS, salt) != visitor.hash_address("203.0.113.58", salt)


@pytest.mark.req("R-10.3-1")
def test_another_salt_gives_another_hash(salt: str) -> None:
    assert visitor.hash_address(ADDRESS, salt) != visitor.hash_address(
        ADDRESS, secrets.token_hex(16)
    )


@pytest.mark.req("R-10.3-7")
def test_hash_does_not_contain_the_address_or_the_salt(salt: str) -> None:
    digest = visitor.hash_address(ADDRESS, salt)

    assert len(digest) == 64
    assert ADDRESS not in digest
    assert salt not in digest


@pytest.mark.req("R-10.3-1")
def test_ipv4_mapped_ipv6_hashes_as_its_ipv4_form(salt: str) -> None:
    assert visitor.hash_address(f"::ffff:{ADDRESS}", salt) == visitor.hash_address(ADDRESS, salt)


@pytest.mark.req("R-10.3-1")
def test_ipv6_addresses_are_reduced_to_their_64_bit_prefix(salt: str) -> None:
    first = visitor.hash_address("2001:db8:1:2::1", salt)
    same_prefix = visitor.hash_address("2001:db8:1:2:aaaa:bbbb:cccc:dddd", salt)
    other_prefix = visitor.hash_address("2001:db8:1:3::1", salt)

    assert first == same_prefix
    assert first != other_prefix


@pytest.mark.req("R-10.3-1")
def test_a_string_that_is_not_an_address_is_hashed_as_given(salt: str) -> None:
    assert visitor.canonical_address("unknown") == "unknown"
    assert visitor.hash_address("unknown", salt) != visitor.hash_address("other", salt)


@pytest.mark.req("R-10.3-2")
def test_right_code_boosts() -> None:
    code = secrets.token_urlsafe(8)

    assert visitor.is_boosted(code, code) is True


@pytest.mark.req("R-10.3-2")
def test_wrong_or_missing_code_does_not_boost() -> None:
    code = secrets.token_urlsafe(8)

    assert visitor.is_boosted(code + "x", code) is False
    assert visitor.is_boosted(code[:-1], code) is False
    assert visitor.is_boosted("", code) is False
    assert visitor.is_boosted(None, code) is False
    assert visitor.is_boosted("çódigo", code) is False


@pytest.mark.req("R-10.3-2")
@pytest.mark.parametrize("configured", [None, ""])
def test_no_configured_code_never_boosts(configured: str | None) -> None:
    assert visitor.is_boosted("anything", configured) is False
    assert visitor.is_boosted("", configured) is False
    assert visitor.is_boosted(None, configured) is False
