import asyncio
import secrets

import pytest

from tests.integration.quoting.conftest import TTL, Env
from veranico.modules.quoting.application.ports import Reservation
from veranico.modules.quoting.application.quotes import idempotency_ref
from veranico.modules.quoting.infrastructure.mapping import IDEMPOTENCY
from veranico.shared.kernel.errors import IdempotencyConflictError
from veranico.shared.kernel.ids import QuoteId

pytestmark = [pytest.mark.integration, pytest.mark.req("R-6-4")]


def _reservation(env: Env, quote_id: str, fingerprint: str = "f" * 64) -> Reservation:
    return Reservation(env.workspace_id, fingerprint, QuoteId(quote_id))


async def test_a_new_key_is_reserved_and_a_second_reservation_returns_the_first(
    env: Env,
) -> None:
    ref = idempotency_ref(env.workspace_id, secrets.token_hex(8))
    first = _reservation(env, "Q-AAAAAA")

    created = await env.idempotency.reserve(ref, first, at=env.start)
    again = await env.idempotency.reserve(
        ref, _reservation(env, "Q-BBBBBB", fingerprint="0" * 64), at=env.start
    )

    assert created == first
    assert again == first
    stored = (await env.client.collection(IDEMPOTENCY).document(ref).get()).to_dict()
    assert stored == {
        "workspace_id": env.workspace_id,
        "fingerprint": "f" * 64,
        "quote_id": "Q-AAAAAA",
        "expires_at": env.start + TTL,
    }


async def test_twenty_reservations_started_together_agree_on_one_quote_id(env: Env) -> None:
    ref = idempotency_ref(env.workspace_id, secrets.token_hex(8))
    wanted = [_reservation(env, f"Q-{number:06d}") for number in range(20)]

    reserved = await asyncio.gather(
        *(env.idempotency.reserve(ref, reservation, at=env.start) for reservation in wanted)
    )

    assert len({reservation.quote_id for reservation in reserved}) == 1
    assert reserved[0] in wanted


async def test_a_replayed_key_returns_the_stored_quote_and_another_payload_conflicts(
    env: Env,
) -> None:
    first = await env.service.create_quote(env.api_key, env.command(), "key-a", "api_client")
    calls = len(env.climate.calls) + len(env.pricing.calls)

    replayed = await env.service.create_quote(env.api_key, env.command(), "key-a", "api_client")
    with pytest.raises(IdempotencyConflictError):
        await env.service.create_quote(
            env.api_key, env.command(label="another"), "key-a", "api_client"
        )

    assert replayed == first
    assert len(env.climate.calls) + len(env.pricing.calls) == calls
    assert len(await env.quotes.list_for_workspace(env.workspace_id)) == 1


@pytest.mark.req("R-10.1-2")
async def test_the_same_key_in_another_workspace_is_an_independent_quote(env: Env) -> None:
    mine = await env.service.create_quote(env.api_key, env.command(), "key-a", "api_client")

    theirs = await env.service.create_quote(env.stranger, env.command(), "key-a", "agent")

    assert theirs.quote_id != mine.quote_id
    assert theirs.workspace_id == env.stranger.workspace_id
    assert [q.quote_id for q in await env.quotes.list_for_workspace(env.workspace_id)] == [
        mine.quote_id
    ]
