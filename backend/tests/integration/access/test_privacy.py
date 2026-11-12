"""No address and no secret reaches a log record or a stored document (SPEC 10.3, 15).

The module is built as the composition root builds it and driven with recognisable values;
then every log record captured and every document the test wrote is searched for them.
"""

import logging
import secrets

import pytest
from google.cloud.firestore import AsyncClient

from tests.fakes.settings import settings_for_tests
from tests.integration.access.conftest import FIRESTORE_HOST
from veranico.modules.access import module as access_module
from veranico.modules.access.contracts import ModelUsage
from veranico.shared.infrastructure.settings import DEFAULT_AGENT_MODEL
from veranico.shared.kernel.clock import FixedClock
from veranico.shared.kernel.errors import ForbiddenError

pytestmark = [pytest.mark.integration, pytest.mark.req("R-10.3-7")]

ADDRESS = "203.0.113.199"  # a documentation address (RFC 5737), easy to recognise
ADDRESS_V6 = "2001:db8:abcd:1234:5678:9abc:def0:1234"


async def test_no_address_and_no_secret_in_any_log_record_or_document(
    firestore: AsyncClient, spend_clock: FixedClock, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    salt = secrets.token_hex(32)
    code = secrets.token_urlsafe(12)
    cookie_secret = secrets.token_hex(32)
    settings = settings_for_tests(
        firestore_emulator_host=FIRESTORE_HOST,
        cookie_signing_secret=cookie_secret,
        access={"ip_hash_salt": salt, "allowance_code": code},
    )
    facade = access_module.build(
        access_module.AccessDeps(settings=settings, clock=spend_clock, firestore=firestore)
    ).facade

    # Workspace and API key, then authentications that are refused.
    principal, _ = await facade.open_workspace(None)
    issued = await facade.issue_api_key(principal)
    key_secret = issued.secret.split("_", 2)[2]
    wrong_secret = secrets.token_urlsafe(32)
    errors: list[ForbiddenError] = []
    for bearer in (f"vrk_{issued.key_id}_{wrong_secret}", f"vrk_0123456789abcdef_{key_secret}"):
        with pytest.raises(ForbiddenError) as raised:
            await facade.authenticate_api_key(bearer)
        errors.append(raised.value)
    await facade.authenticate_api_key(issued.secret)

    # The visitor, with and without the code, over both address families, to exhaustion.
    visitor = facade.visitor(ADDRESS, None)
    boosted = facade.visitor(ADDRESS, code)
    visitor_v6 = facade.visitor(ADDRESS_V6, "a-wrong-code")
    await facade.allowance(visitor)
    await facade.allowance(visitor_v6)
    admissions = [await facade.admit_message(visitor, new_conversation=False) for _ in range(16)]
    assert [admission.allowed for admission in admissions] == [True] * 15 + [False]
    assert (await facade.admit_message(boosted, new_conversation=True)).allowed
    assert (await facade.admit_message(visitor_v6, new_conversation=True)).allowed
    await facade.record_spend(
        ModelUsage(model=DEFAULT_AGENT_MODEL, input_tokens=1_000, output_tokens=200)
    )
    await facade.may_spend()

    # Every document of the four collections this test wrote.
    now = spend_clock.now()
    references = [
        firestore.collection("access_workspaces").document(principal.workspace_id),
        firestore.collection("access_api_keys").document(issued.key_id),
        firestore.collection("access_allowances").document(f"{visitor.ip_hash}-{now:%Y%m%d}"),
        firestore.collection("access_allowances").document(f"{visitor_v6.ip_hash}-{now:%Y%m%d}"),
        firestore.collection("access_spend").document(f"day-{now:%Y-%m-%d}"),
        firestore.collection("access_spend").document(f"month-{now:%Y-%m}"),
    ]
    stored: list[str] = []
    for reference in references:
        snapshot = await reference.get()
        assert snapshot.exists, reference.path
        stored.append(f"{reference.path} {snapshot.to_dict()!r}")
    logged = [
        f"{record.name} {record.getMessage()} {record.args!r} {record.exc_text or ''}"
        for record in caplog.records
    ]
    raised_texts = [f"{error!s} {error!r} {error.detail!r}" for error in errors]
    returned = [repr(visitor), repr(boosted), repr(visitor_v6), repr(admissions[-1])]

    forbidden_everywhere = {
        "the address": ADDRESS,
        "the IPv6 address": ADDRESS_V6,
        "the IPv6 prefix": "2001:db8:abcd:1234",
        "the salt": salt,
        "the boost code": code,
        "the cookie signing secret": cookie_secret,
        "the key secret": key_secret,
        "the bearer": issued.secret,
        "the wrong secret": wrong_secret,
    }
    for what, value in forbidden_everywhere.items():
        for text in stored + logged + raised_texts + returned:
            assert value not in text, f"{what} appears in: {text[:80]}"
