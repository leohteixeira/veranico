import pytest

from tests.fakes.access import FakeAccessFacade
from veranico.modules.access.contracts import ModelUsage
from veranico.shared.kernel.errors import ForbiddenError, RateLimitedError
from veranico.shared.kernel.ids import WorkspaceId
from veranico.shared.kernel.principal import Principal

USAGE = ModelUsage(model="claude-haiku-5-5", input_tokens=100, output_tokens=20)


async def test_open_workspace_returns_the_same_workspace_and_no_cookie_for_its_own_cookie() -> None:
    access = FakeAccessFacade()
    first, cookie = await access.open_workspace(None)
    assert cookie is not None

    again, new_cookie = await access.open_workspace(cookie)

    assert again == first
    assert new_cookie is None
    assert first.kind == "browser"


async def test_open_workspace_treats_a_cookie_it_did_not_issue_as_absent() -> None:
    access = FakeAccessFacade()
    first, cookie = await access.open_workspace(None)

    other, other_cookie = await access.open_workspace("a-cookie-from-elsewhere")

    assert other.workspace_id != first.workspace_id
    assert other_cookie is not None
    assert other_cookie not in {cookie, "a-cookie-from-elsewhere"}


async def test_authenticate_api_key_raises_forbidden_for_an_unknown_key() -> None:
    access = FakeAccessFacade()

    with pytest.raises(ForbiddenError):
        await access.authenticate_api_key("unknown")


async def test_an_issued_key_authenticates_as_its_workspace() -> None:
    access = FakeAccessFacade()
    browser, _ = await access.open_workspace(None)
    issued = await access.issue_api_key(browser)

    principal = await access.authenticate_api_key(issued.secret)

    assert principal == Principal(
        workspace_id=browser.workspace_id, kind="api_key", key_id=issued.key_id
    )


@pytest.mark.parametrize("kind", ["api_key", "system"])
async def test_issue_api_key_is_only_for_browser_principals(kind: str) -> None:
    access = FakeAccessFacade()
    principal = Principal(workspace_id=WorkspaceId("ws-1"), kind=kind, key_id="key-1")

    with pytest.raises(ForbiddenError):
        await access.issue_api_key(principal)


async def test_check_rate_raises_for_a_key_marked_rate_limited() -> None:
    access = FakeAccessFacade()
    browser, _ = await access.open_workspace(None)
    issued = await access.issue_api_key(browser)
    principal = await access.authenticate_api_key(issued.secret)
    await access.check_rate(principal)

    access.rate_limited.add(issued.key_id)

    with pytest.raises(RateLimitedError):
        await access.check_rate(principal)


async def test_admit_message_consumes_only_when_allowed() -> None:
    access = FakeAccessFacade(conversations=1, messages=2)
    visitor = access.visitor("203.0.113.9", None)

    first = await access.admit_message(visitor, new_conversation=True)
    second = await access.admit_message(visitor, new_conversation=False)
    refused = await access.admit_message(visitor, new_conversation=False)
    refused_again = await access.admit_message(visitor, new_conversation=True)

    assert (first.allowed, first.reason) == (True, "ok")
    assert first.allowance is not None
    assert (first.allowance.conversations_left, first.allowance.messages_left) == (0, 1)
    assert second.allowed
    assert (refused.allowed, refused.reason) == (False, "visitor_allowance")
    assert not refused_again.allowed
    left = await access.allowance(visitor)
    assert (left.conversations_left, left.messages_left) == (0, 0)


async def test_a_second_conversation_is_refused_and_consumes_no_message() -> None:
    access = FakeAccessFacade(conversations=1, messages=5)
    visitor = access.visitor("203.0.113.9", None)
    await access.admit_message(visitor, new_conversation=True)

    refused = await access.admit_message(visitor, new_conversation=True)

    assert (refused.allowed, refused.reason) == (False, "visitor_allowance")
    assert (await access.allowance(visitor)).messages_left == 4


async def test_the_allowance_code_gives_the_boosted_allowance() -> None:
    access = FakeAccessFacade()

    plain = await access.allowance(access.visitor("203.0.113.9", None))
    wrong = await access.allowance(access.visitor("203.0.113.9", "wrong-code"))
    boosted = await access.allowance(access.visitor("203.0.113.9", "test-allowance-code"))

    assert (plain.boosted, plain.conversations_left, plain.messages_left) == (False, 2, 15)
    assert wrong == plain
    assert (boosted.boosted, boosted.conversations_left, boosted.messages_left) == (True, 6, 60)


async def test_spending_is_driven_by_the_settable_ceiling() -> None:
    access = FakeAccessFacade()
    access.ceiling_usd_micros = 200
    visitor = access.visitor("203.0.113.9", None)

    before = await access.may_spend()
    recorded = await access.record_spend(USAGE)
    under = await access.may_spend()
    await access.record_spend(USAGE)
    over = await access.may_spend()
    admission = await access.admit_message(visitor, new_conversation=True)

    assert before.allowed
    assert before.allowance is None
    assert recorded.cost_usd_micros == access.cost_of(USAGE) == 120
    assert under.allowed
    assert (over.allowed, over.reason, over.allowance) == (False, "day_ceiling", None)
    assert (admission.allowed, admission.reason) == (False, "day_ceiling")
    assert (await access.allowance(visitor)).messages_left == 15  # nothing consumed


async def test_calls_lists_what_was_received_in_order() -> None:
    access = FakeAccessFacade()
    visitor = access.visitor("203.0.113.9", None)
    await access.admit_message(visitor, new_conversation=True)
    await access.may_spend()
    await access.record_spend(USAGE)

    assert access.calls == [
        ("visitor", ("203.0.113.9", None)),
        ("admit_message", (visitor, True)),
        ("may_spend", ()),
        ("record_spend", (USAGE,)),
    ]
