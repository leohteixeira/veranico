import pytest

from tests.api.assistant.conftest import V1, AssistantApi, sse_events
from tests.unit.assistant.tools.kit import BROWSER
from veranico.modules.assistant.application.replay import Replays

pytestmark = [pytest.mark.integration, pytest.mark.req("R-9.6-2", "R-11.2-3")]

LOCALES = ("en", "pt-BR")


@pytest.mark.parametrize("locale", LOCALES)
async def test_replay_streams_recorded_turns_in_both_locales(
    api: AssistantApi, locale: str
) -> None:
    response = await api.browser(api.app()).get(f"{V1}/replays/{locale}")

    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/event-stream")
    events = sse_events(response.text)
    recorded = Replays().events(locale)  # type: ignore[arg-type]  # the parameter is one of the two locales
    assert [data for _, data in events] == [event.model_dump(mode="json") for event in recorded]
    names = [name for name, _ in events]
    assert names[0] == "started"
    assert names[-1] == "done"
    assert names.count("started") == names.count("done") >= 1


@pytest.mark.parametrize("locale", LOCALES)
async def test_replay_carries_each_recorded_request_as_a_user_message_event(
    api: AssistantApi, locale: str
) -> None:
    response = await api.browser(api.app()).get(f"{V1}/replays/{locale}")

    events = sse_events(response.text)
    for index, (name, _) in enumerate(events):
        if name == "started":
            following, data = events[index + 1]
            assert following == "user_message"
            assert data["text"].strip()
    assert [name for name, _ in events].count("user_message") == (
        [name for name, _ in events].count("started")
    )


async def test_replay_creates_no_quote_and_no_approval(api: AssistantApi) -> None:
    browser = api.browser(api.app())
    fakes = (api.tools.climate, api.tools.pricing, api.tools.quoting, api.tools.carriers)
    for fake in fakes:
        fake.calls.clear()  # building the module reads the carrier catalogue

    for locale in LOCALES:
        assert (await browser.get(f"{V1}/replays/{locale}")).status_code == 200

    for fake in fakes:
        assert fake.calls == []
    assert await api.tools.quoting.list_quotes(BROWSER) == []
    assert await api.tools.quoting.list_approvals(BROWSER, None) == []
    # No model call and no charge either: only the workspace was opened.
    assert {name for name, _ in api.access.calls} == {"open_workspace"}


async def test_replay_unknown_locale_is_a_problem(api: AssistantApi) -> None:
    response = await api.browser(api.app()).get(f"{V1}/replays/fr")

    assert response.status_code == 422
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["code"] == "invalid_arguments"
