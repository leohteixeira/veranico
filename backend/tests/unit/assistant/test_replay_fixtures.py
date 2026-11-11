"""The recorded conversation of each language (SPEC 9.6).

The recordings are made with the real model on the real cubes, which need human gate H1 (the
Copernicus account), by `uv run python -m tests.evals.record_replay --locale <locale>`. Until
then `replays/<locale>.jsonl` are placeholders, marked `"placeholder": true` in their metadata
line, and the test of the recording is skipped: a skipped test proves nothing, so the
requirement stays open. Once a recording replaces a placeholder the test runs, and it fails
unless the recording is the full flow of the real model on the real cubes. The checks are the
recorder's own (`recording_problems`, `not_real`); `tests/integration/assistant/
test_record_replay.py` runs them on a recording of the scripted flow.
"""

from importlib import resources

import pytest

from tests.evals.record_replay import load_prompts, not_real, recording_problems
from veranico.modules.assistant.application.replay import LOCALES, parse_recording
from veranico.shared.kernel.ids import Locale


def recording(locale: Locale) -> str:
    return (
        resources.files("veranico.modules.assistant.replays")
        .joinpath(f"{locale}.jsonl")
        .read_text(encoding="utf-8")
    )


@pytest.mark.parametrize("locale", LOCALES)
def test_both_recordings_exist_and_parse_as_agent_events(locale: Locale) -> None:
    metadata, events = parse_recording(recording(locale))

    assert metadata
    assert events


@pytest.mark.req("R-9.6-1")
@pytest.mark.parametrize("locale", LOCALES)
def test_the_recording_is_the_full_flow_made_with_the_model(locale: Locale) -> None:
    metadata, events = parse_recording(recording(locale))
    if metadata.get("placeholder"):
        pytest.skip("placeholder recording: the real one is recorded after human gate H1")

    assert recording_problems(metadata, events, load_prompts(locale), locale) == []
    assert not_real(metadata) == []
