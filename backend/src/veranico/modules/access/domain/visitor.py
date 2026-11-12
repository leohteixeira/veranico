"""Who a visitor is, without keeping the address: a keyed hash and the boost flag."""

import hashlib
import hmac
import ipaddress


def canonical_address(address: str) -> str:
    """The form of an address that is hashed.

    An IPv4-mapped IPv6 address becomes IPv4, so one client has one identity on both
    stacks. Any other IPv6 address is reduced to its /64 prefix: a host chooses the low
    64 bits freely, and each choice would otherwise be a new visitor with a fresh
    allowance. A string that is not an address is kept as given.
    """
    try:
        parsed = ipaddress.ip_address(address.strip())
    except ValueError:
        return address
    if isinstance(parsed, ipaddress.IPv6Address):
        if parsed.ipv4_mapped is not None:
            return str(parsed.ipv4_mapped)
        return str(ipaddress.ip_network((int(parsed) >> 64 << 64, 64)))
    return str(parsed)


def hash_address(address: str, salt: str) -> str:
    """Hex HMAC SHA-256 of the canonical address under the salt."""
    return hmac.new(salt.encode(), canonical_address(address).encode(), hashlib.sha256).hexdigest()


def is_boosted(code: str | None, configured_code: str | None) -> bool:
    """Constant-time comparison with the allowance code; false when none is configured."""
    if not code or not configured_code:
        return False
    return hmac.compare_digest(code.encode(), configured_code.encode())
