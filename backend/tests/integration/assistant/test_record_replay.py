"""The replay recorder end to end, with the scripted model in place of the paid one.

    docker compose -p veranico up -d --wait firestore storage
    uv run pytest tests/integration/assistant/test_record_replay.py -q

The recorder runs as the owner ran it at gate H1, on the whole application, except
that the model client is scripted and the weather is a generated cube of the Sul de Minas
region. Every recording goes to a temporary path, never to the versioned fixtures.
"""

from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

import pytest

from tests.evals import record_replay
from tests.evals.harness import install_synthetic_cubes
from tests.evals.record_replay import (
    EXIT_FAILED,
    EXIT_REFUSED,
    EXIT_WRITTEN,
    SYNTHETIC_NOTE,
    load_prompts,
    not_real,
    recording_problems,
)
from veranico.modules.access.contracts import ModelUsage
from veranico.modules.assistant.application.ports import ModelCompleted, ModelRequest
from veranico.modules.assistant.application.replay import parse_recording
from veranico.modules.assistant.contracts import Started
from veranico.modules.assistant.infrastructure.scripted_model import (
    Played,
    ScriptedModelClient,
    happy_path_policy,
)
from veranico.shared.infrastructure.settings import Settings

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def weather_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("weather")
    install_synthetic_cubes(root, ["sul-de-minas"])
    return root


class Scripted:
    """A model factory that keeps the client it built, to count its calls."""

    def __init__(self, client: ScriptedModelClient) -> None:
        self.client = client

    def __call__(self, settings: Settings) -> ScriptedModelClient:
        return self.client


def record(tmp_path: Path, weather_root: Path, factory: Scripted, *extra: str) -> tuple[int, Path]:
    output = tmp_path / "out" / "en.jsonl"
    code = record_replay.main(
        ["--locale", "en", "--output", str(output), "--weather-root", str(weather_root), *extra],
        environ={},
        model_factory=factory,
        rejected=tmp_path / "rejected",
    )
    return code, output


def costly(request: ModelRequest) -> Played:
    """The happy path, each call reporting a thousand input tokens (more than US$ 0.0001)."""
    played = happy_path_policy(request)
    usage = ModelUsage(model=request.model, input_tokens=1_000, output_tokens=0)
    assert isinstance(played, Sequence)
    return [replace(e, usage=usage) if isinstance(e, ModelCompleted) else e for e in played]


# No requirement marker: a scripted recording on synthetic cubes proves the recorder, not
# R-9.6-1, which the real recordings prove (`tests/unit/assistant/test_replay_fixtures.py`).
def test_a_recording_of_the_scripted_flow_passes_the_checks_of_the_fixtures(
    tmp_path: Path, weather_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    factory = Scripted(ScriptedModelClient.happy_path())

    code, output = record(tmp_path, weather_root, factory, "--allow-synthetic")

    assert code == EXIT_WRITTEN, capsys.readouterr().err
    metadata, events = parse_recording(output.read_text(encoding="utf-8"))
    assert recording_problems(metadata, events, load_prompts("en"), "en") == []
    assert "placeholder" not in metadata
    assert metadata["prompt_version"] == "v5"
    # Labelled for what it is, so the fixture test would reject it as a real recording.
    assert metadata["data_source"] == "synthetic"
    assert metadata["synthetic"] is True
    assert metadata["note"] == SYNTHETIC_NOTE
    assert metadata["model"] == "scripted"
    assert len(not_real(metadata)) == 2
    printed = capsys.readouterr()
    assert "cost of this run: US$ 0.000000 (limit US$ 0.100000)" in printed.out
    assert "NOT REAL" in printed.err
    assert not (tmp_path / "rejected").exists()


def test_the_checks_name_each_way_a_recording_falls_short(
    tmp_path: Path, weather_root: Path
) -> None:
    code, output = record(
        tmp_path, weather_root, Scripted(ScriptedModelClient.happy_path()), "--allow-synthetic"
    )
    assert code == EXIT_WRITTEN
    metadata, events = parse_recording(output.read_text(encoding="utf-8"))
    prompts = load_prompts("en")
    without_submission = tuple(e for e in events if getattr(e, "tool", "") != "request_submission")

    assert recording_problems({**metadata, "placeholder": True}, events, prompts, "en")
    assert recording_problems({**metadata, "data_source": "era5-land/cds"}, events, prompts, "en")
    assert recording_problems(metadata, events, prompts[:-1], "en")
    assert recording_problems(metadata, events, prompts, "pt-BR")
    assert recording_problems(metadata, without_submission, prompts, "en")
    started = events[0]
    assert isinstance(started, Started)
    assert recording_problems(metadata, events, prompts, "en", forbidden=[started.conversation_id])


def test_the_cost_limit_stops_the_run_and_writes_no_recording(
    tmp_path: Path, weather_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    factory = Scripted(ScriptedModelClient(costly))

    code, output = record(
        tmp_path, weather_root, factory, "--allow-synthetic", "--max-cost-usd", "0.0001"
    )

    assert code == EXIT_FAILED
    assert not output.exists()
    assert len(factory.client.requests) == 1  # the call that passed the limit was the last
    printed = capsys.readouterr()
    assert "STOPPED BY THE COST LIMIT" in printed.out
    assert "the cost limit stopped the run" in printed.err
    assert (tmp_path / "rejected" / "en.rejected.jsonl").exists()


def test_synthetic_cubes_are_refused_before_any_model_call(
    tmp_path: Path, weather_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    factory = Scripted(ScriptedModelClient.happy_path())

    code, output = record(tmp_path, weather_root, factory)

    assert code == EXIT_REFUSED
    assert not output.exists()
    assert factory.client.requests == []
    assert "--allow-synthetic" in capsys.readouterr().err
