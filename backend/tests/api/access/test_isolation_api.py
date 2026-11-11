import pytest

from tests.api.access.conftest import AccessApi
from veranico.shared.kernel.errors import ForbiddenError

pytestmark = pytest.mark.integration

URL = "/api/v1/workspace/api-keys"


async def _workspace_of_key(api: AccessApi, secret: str) -> str:
    return (await api.facade.authenticate_api_key(secret)).workspace_id


@pytest.mark.req("R-10.2-2", "R-10.1-2")
async def test_another_browser_gets_another_workspace_and_its_key_opens_only_that_one(
    api: AccessApi,
) -> None:
    first, second = api.browser(), api.browser()

    first_key = (await first.post(URL)).json()
    second_key = (await second.post(URL)).json()

    first_workspace, _ = await api.facade.open_workspace(first.cookies["vr_ws"])
    second_workspace, _ = await api.facade.open_workspace(second.cookies["vr_ws"])
    assert first_workspace.workspace_id != second_workspace.workspace_id
    assert await _workspace_of_key(api, first_key["secret"]) == first_workspace.workspace_id
    assert await _workspace_of_key(api, second_key["secret"]) == second_workspace.workspace_id
    # The id of one key with the secret of the other opens nothing.
    crossed = f"vrk_{first_key['key_id']}_{second_key['secret'].split('_', 2)[2]}"
    with pytest.raises(ForbiddenError):
        await api.facade.authenticate_api_key(crossed)


@pytest.mark.req("R-10.1-1", "R-10.1-2")
async def test_a_tampered_cookie_gets_a_new_workspace_and_not_the_old_one(api: AccessApi) -> None:
    victim, attacker = api.browser(), api.browser()
    await victim.post(URL)
    await attacker.post(URL)
    victim_workspace, _ = await api.facade.open_workspace(victim.cookies["vr_ws"])
    attacker_workspace, _ = await api.facade.open_workspace(attacker.cookies["vr_ws"])
    # The attacker's own valid cookie, rewritten to name the victim's workspace.
    version, _, expires, signature = attacker.cookies["vr_ws"].split(".")
    forged = f"{version}.{victim_workspace.workspace_id}.{expires}.{signature}"
    intruder = api.browser()

    response = await intruder.post(URL, headers={"Cookie": f"vr_ws={forged}"})

    assert response.status_code == 200  # no access gate: a new workspace, never an error
    assert response.headers["set-cookie"].startswith("vr_ws=v1.")
    workspace = await _workspace_of_key(api, response.json()["secret"])
    assert workspace not in (victim_workspace.workspace_id, attacker_workspace.workspace_id)


@pytest.mark.req("R-10.2-1", "R-10.1-2")
async def test_a_bearer_instead_of_a_cookie_does_not_mint_a_key_for_the_keys_workspace(
    api: AccessApi,
) -> None:
    owner = api.browser()
    key = (await owner.post(URL)).json()
    owner_workspace = await _workspace_of_key(api, key["secret"])
    client = api.browser()  # no cookie, only the stolen or integrated key

    response = await client.post(URL, headers={"Authorization": f"Bearer {key['secret']}"})

    # The route is a browser route: the bearer is ignored and a new, empty workspace opens.
    assert response.status_code == 200
    assert response.headers["set-cookie"].startswith("vr_ws=v1.")
    assert await _workspace_of_key(api, response.json()["secret"]) != owner_workspace
