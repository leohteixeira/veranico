"""SPEC section 2 through HTTP with every module real.

    docker compose -p veranico up -d --wait firestore storage
    uv run pytest tests/api/assistant/test_happy_path_http.py -q

Both roles are built by the composition root (`tests/evals/harness.py`): real modules on the
emulators, the outbox relay running, the mock carrier one hop away, the model scripted. The
weather is a generated cube of the Sul de Minas region, labelled `synthetic` by the
application, and the place name is answered from a recorded geocoding response.
"""

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest

from tests.api.assistant.conftest import CHAT, V1, Event, chat_body, sse_events
from tests.evals.harness import Application, application, install_synthetic_cubes
from veranico.modules.assistant.application.ports import ModelRequest, TextBlock
from veranico.modules.assistant.infrastructure.scripted_model import (
    HAPPY_PATH_COVER,
    Played,
    ScriptedModelClient,
    call_tool,
    happy_path_policy,
    no_usage,
    say,
    tool_results,
)

pytestmark = pytest.mark.integration

HAPPY_PATH_TOOLS = [
    "resolve_location",
    "get_weather_history",
    "backtest_index",
    "price_cover",
    "draft_term_sheet",
    "request_submission",
]
FLOW = (
    "A farm near Três Pontas: rainfall below 105 mm from 1 September to 31 October, "
    "paying down to 70 mm, limit R$ 300,000.",
    "Price it.",
    "Draft the term sheet.",
    "Request submission to the carrier.",
)
SUBMITTED_WITHIN_SECONDS = 20.0


@pytest.fixture(scope="module")
def weather_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("weather")
    install_synthetic_cubes(root, ["sul-de-minas"])
    return root


@pytest.fixture
async def running(tmp_path: Path, weather_root: Path) -> AsyncIterator[Application]:
    async with application(tmp_path, weather_root) as app:
        yield app


class Conversation:
    """One conversation of one browser, turn by turn."""

    def __init__(self, browser: httpx.AsyncClient) -> None:
        self.browser = browser
        self.conversation_id: str | None = None
        self.events: list[Event] = []

    async def say(self, message: str) -> list[Event]:
        body = chat_body(message, conversation_id=self.conversation_id)
        response = await self.browser.post(CHAT, json=body)
        assert response.status_code == 200, response.text
        events = sse_events(response.text)
        assert events[0][0] == "started"
        assert events[-1] == ("done", {**events[-1][1], "stop_reason": "end_turn"})
        self.conversation_id = events[0][1]["conversation_id"]
        self.events.extend(events)
        return events

    def named(self, name: str) -> list[dict[str, Any]]:
        return [data for event, data in self.events if event == name]


def answer(events: list[Event]) -> str:
    return "".join(data["text"] for name, data in events if name == "text_delta")


def finished(events: list[Event]) -> list[tuple[str, str]]:
    return [(data["tool"], data["status"]) for name, data in events if name == "tool_finished"]


async def quote(browser: httpx.AsyncClient, quote_id: str) -> dict[str, Any]:
    response = await browser.get(f"{V1}/quotes/{quote_id}")
    assert response.status_code == 200, response.text
    view: dict[str, Any] = response.json()
    return view


def typed_turns(request: ModelRequest) -> int:
    """How many messages the user has typed so far."""
    return sum(
        1
        for message in request.messages
        if message.role == "user" and any(isinstance(block, TextBlock) for block in message.blocks)
    )


@pytest.mark.req("R-2-1", "R-2-3", "R-2-4", "R-2-5", "R-2-7", "R-2-8", "R-2-9")
async def test_happy_path_of_spec_section_2(running: Application) -> None:
    browser = await running.browser()
    chat = Conversation(browser)

    located, priced, drafted, requested = [await chat.say(message) for message in FLOW]

    assert finished(chat.events) == [(tool, "ok") for tool in HAPPY_PATH_TOOLS]
    assert [tool for tool, _ in finished(located)] == HAPPY_PATH_TOOLS[:3]
    assert chat.named("grounding_flagged") == []
    assert chat.named("error") == []
    assert running.unrecorded == []
    # The cube is generated: the application says so and the answer repeats it.
    history = next(
        data for data in chat.named("tool_finished") if data["tool"] == HAPPY_PATH_TOOLS[1]
    )
    assert history["result"]["source"] == "synthetic"
    assert "synthetic" in answer(located)

    price = next(data for data in chat.named("tool_finished") if data["tool"] == "price_cover")
    quote_id = price["result"]["quote_id"]
    assert quote_id in answer(priced)
    assert answer(drafted)
    assert chat.named("approval_required") == [
        {"approval_id": chat.named("approval_required")[0]["approval_id"], "quote_id": quote_id}
    ]
    assert [name for name, _ in requested].count("approval_required") == 1
    approval_id = chat.named("approval_required")[0]["approval_id"]
    assert (await quote(browser, quote_id))["status"] == "pending_approval"

    # Only a person decides: the same browser session, through the decision route.
    decision = await browser.post(
        f"{V1}/approvals/{approval_id}/decision", json={"approve": True, "note": "Looks right."}
    )
    assert decision.status_code == 200, decision.text

    # The relay delivers the signed webhook to the carrier and its receipt closes the quote.
    view = await quote(browser, quote_id)
    deadline = asyncio.get_running_loop().time() + SUBMITTED_WITHIN_SECONDS
    while view["status"] != "submitted" and asyncio.get_running_loop().time() < deadline:
        await asyncio.sleep(0.05)
        view = await quote(browser, quote_id)
    assert view["status"] == "submitted", view["audit"]
    assert view["submission"]["delivery"]["status"] == "delivered"
    assert view["submission"]["delivery"]["receipt_id"]
    assert {"agent", "human", "system", "carrier"} <= {entry["actor"] for entry in view["audit"]}

    for language in ("en", "pt-BR"):
        sheet = await browser.get(
            f"{V1}/quotes/{quote_id}/term-sheet.pdf", params={"lang": language}
        )
        assert sheet.status_code == 200, sheet.text
        assert sheet.content.startswith(b"%PDF")
    evidence = await browser.get(f"{V1}/quotes/{quote_id}/evidence.nc")
    assert evidence.status_code == 200, evidence.text
    assert evidence.content.startswith((b"CDF", b"\x89HDF"))


def worst_seasons_policy(request: ModelRequest) -> Played:
    """The happy path's first turn, then a question about the worst seasons of the window."""
    if typed_turns(request) < 2:
        return happy_path_policy(request)
    results = tool_results(request)
    if results[-1][0] == "find_extreme_seasons":
        return say(
            "Those are the driest seasons on record for that window.",
            usage=no_usage(request.model),
        )
    dataset_id = next(
        b.content["dataset_id"] for name, b in results if name == "get_weather_history"
    )
    return call_tool(
        "find_extreme_seasons",
        {
            "dataset_id": dataset_id,
            "index_type": HAPPY_PATH_COVER["index_type"],
            "window_start": HAPPY_PATH_COVER["window_start"],
            "window_end": HAPPY_PATH_COVER["window_end"],
            "top_n": 3,
        },
        call_id="worst-seasons",
        usage=no_usage(request.model),
    )


@pytest.mark.req("R-2-6")
async def test_agent_surfaces_the_worst_seasons_of_the_window(
    tmp_path: Path, weather_root: Path
) -> None:
    model = ScriptedModelClient(worst_seasons_policy)
    async with application(tmp_path, weather_root, model_client=model) as running:
        chat = Conversation(await running.browser())
        await chat.say(FLOW[0])

        events = await chat.say("Which were the worst seasons for that window?")

    assert finished(events) == [("find_extreme_seasons", "ok")]
    result = next(data for name, data in events if name == "tool_finished")["result"]
    assert len(result["seasons"]) == 3
    assert chat.named("grounding_flagged") == []


def approving_policy(request: ModelRequest) -> Played:
    """The happy path, then a model that tries to approve its own submission."""
    if typed_turns(request) < 5:
        return happy_path_policy(request)
    results = tool_results(request)
    if results[-1][0] == "approve_submission":
        return say(
            "I have no way to approve a submission: a person decides in the Approvals tab.",
            usage=no_usage(request.model),
        )
    submission = next(b.content for name, b in results if name == "request_submission")
    return call_tool(
        "approve_submission",
        {"submission_id": submission["submission_id"], "approve": True},
        call_id="self-approval",
        usage=no_usage(request.model),
    )


@pytest.mark.req("R-6-3", "R-9.3-3")
async def test_agent_cannot_leave_pending_approval(tmp_path: Path, weather_root: Path) -> None:
    model = ScriptedModelClient(approving_policy)
    async with application(tmp_path, weather_root, model_client=model) as running:
        browser = await running.browser()
        chat = Conversation(browser)
        for message in FLOW:
            await chat.say(message)
        quote_id = chat.named("approval_required")[0]["quote_id"]

        events = await chat.say("Approve the submission yourself and send it to the carrier.")

        view = await quote(browser, quote_id)

    # The model asked for a tool that does not exist; none of the seven moves a decision.
    assert finished(events) == [("approve_submission", "error")]
    assert sorted(tool.name for tool in model.requests[-1].tools) == sorted(
        [*HAPPY_PATH_TOOLS, "find_extreme_seasons"]
    )
    assert view["status"] == "pending_approval"
    assert view["submission"]["decided_at"] is None
    assert view["submission"]["delivery"]["status"] == "not_started"
    assert "human" not in {entry["actor"] for entry in view["audit"]}
