"""The recorded conversation of each language (SPEC 9.6).

The recordings are made with the real model on the real cubes, which need human gate H1 (the
Copernicus account). Until then `replays/<locale>.jsonl` are placeholders, marked
`"placeholder": true` in their metadata line, and this test is skipped: a skipped test proves
nothing, so the requirement stays open. Once a recording replaces a placeholder the test
runs, and it fails unless the recording is the full flow.
"""

from importlib import resources

import pytest

from veranico.modules.assistant.application.replay import LOCALES, parse_recording
from veranico.modules.assistant.contracts import (
    ApprovalRequired,
    GroundingFlagged,
    ToolFinished,
    UserMessage,
)

FULL_FLOW = [
    "resolve_location",
    "get_weather_history",
    "backtest_index",
    "price_cover",
    "draft_term_sheet",
    "request_submission",
]


@pytest.mark.req("R-9.6-1")
@pytest.mark.parametrize("locale", LOCALES)
def test_the_recording_is_the_full_flow_made_with_the_model(locale: str) -> None:
    text = (
        resources.files("veranico.modules.assistant.replays")
        .joinpath(f"{locale}.jsonl")
        .read_text(encoding="utf-8")
    )
    metadata, events = parse_recording(text)
    if metadata.get("placeholder"):
        pytest.skip("placeholder recording: the real one is recorded after human gate H1")

    assert metadata["model"] not in (None, "none")
    assert str(metadata["prompt_version"]).startswith("v")
    assert metadata["data_source"] != "synthetic", "record on the real cubes, after gate H1"
    ran = [
        event.tool for event in events if isinstance(event, ToolFinished) and event.status == "ok"
    ]
    position = 0
    for tool in FULL_FLOW:
        assert tool in ran[position:], f"{tool} is missing from the recorded flow, or out of order"
        position = ran.index(tool, position) + 1
    assert any(isinstance(event, ApprovalRequired) for event in events)
    assert any(isinstance(event, UserMessage) for event in events)
    assert not any(isinstance(event, GroundingFlagged) for event in events)
