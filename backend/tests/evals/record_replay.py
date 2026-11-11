"""Record the conversation the interface replays when a visitor may not chat (SPEC 9.6).

    uv run python -m tests.evals.record_replay --locale en --max-cost-usd 0.10
    uv run python -m tests.evals.record_replay --locale pt-BR --max-cost-usd 0.10

This calls the paid model API. Run it only after human gate H1, on the real cubes of the three
showcase regions (`make build-cube REGION=...` without `SYNTHETIC=1`), and only when the
remaining budget covers it. It needs `ANTHROPIC_API_KEY` in the environment and the emulators
(`docker compose -p veranico up -d --wait firestore storage`).

The user messages of `replay_prompts.yaml` go, in order, through the real loop and the real
tools of the whole application (`harness.application`: every module on the emulators, the
mock carrier one hop away, the place name answered from the recorded geocoding answers). The
recording is the file the replay player reads (`application/replay.py`): a metadata line, then
per turn its `started`, one `user_message` with the request of that turn, the events of the
turn and its `done`.

The recorder writes the file only when the recording passes `recording_problems`, the checks
`tests/unit/assistant/test_replay_fixtures.py` runs on the versioned recordings: the full flow
in order, an approval request, no grounding flag, every answer grounded and in the locale's
language, no secret. A recording that fails, or a run the cost limit stopped, is written to
`.cache/replays/` for reading instead and the fixture is left alone. Review a written
recording by reading it before committing it; every run counts against the budget.

`--max-cost-usd` is a hard stop (default US$ 0.10): no model call is made once the run has
spent it, so a run passes it by at most one call. The cost is measured token usage times the
configured prices (`AccessFacade.cost_of`), printed at the end.

Synthetic cubes are refused: a recording made on them would show generated figures as a real
conversation. `--allow-synthetic` records anyway and labels the metadata `synthetic`; such a
recording must not be presented as real and fails the fixture test until it is recorded again
on the real cubes.

Exit codes: 0 written; 1 failed (emulators down, the run stopped by the cost limit, or the
recording failed its checks); 2 refused (synthetic cubes without `--allow-synthetic`, or bad
arguments); 3 `ANTHROPIC_API_KEY` is missing.
"""

import argparse
import asyncio
import json
import os
import re
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import yaml

from tests.evals.checks import classify_language
from tests.evals.driver import VISITOR_ADDRESS, MeteredModel, Spend, usd, usd_micros
from tests.evals.harness import EmulatorDownError, application, require_emulators
from veranico.modules.assistant.application.ports import ModelClient
from veranico.modules.assistant.application.replay import EVENT_NAMES, LOCALES, parse_recording
from veranico.modules.assistant.contracts import (
    AgentEvent,
    ApprovalRequired,
    ChatRequest,
    Done,
    GroundingFlagged,
    Started,
    StreamError,
    TextDelta,
    ToolFinished,
    UserMessage,
)
from veranico.modules.assistant.domain.grounding import check_grounding
from veranico.modules.assistant.infrastructure.anthropic_model import AnthropicModelClient
from veranico.shared.infrastructure.settings import Settings
from veranico.shared.kernel.ids import ConversationId, Locale

BACKEND: Final = Path(__file__).resolve().parents[2]
REPOSITORY: Final = BACKEND.parent
PROMPTS: Final = Path(__file__).resolve().parent / "replay_prompts.yaml"
FIXTURES: Final = BACKEND / "src" / "veranico" / "modules" / "assistant" / "replays"
REJECTED: Final = REPOSITORY / ".cache" / "replays"
DEFAULT_WEATHER: Final = BACKEND / ".data" / "weather"  # `make build-cube` writes here
KEY_VARIABLE: Final = "ANTHROPIC_API_KEY"
DEFAULT_MAX_COST_USD: Final = "0.10"
EXIT_WRITTEN, EXIT_FAILED, EXIT_REFUSED, EXIT_OPEN = 0, 1, 2, 3

# Resolve, history, backtest, price, term sheet, submission; the seventh step of the flow is
# the `approval_required` event the submission raises.
FULL_FLOW: Final = (
    "resolve_location",
    "get_weather_history",
    "backtest_index",
    "price_cover",
    "draft_term_sheet",
    "request_submission",
)
REAL_SOURCE: Final = "era5-land/cds"
DATA_SOURCES: Final = (REAL_SOURCE, "era5/open-meteo", "synthetic")
SCRIPTED_MODEL: Final = "scripted"
SYNTHETIC_NOTE: Final = (
    "Recorded on synthetic cubes: generated data, not weather history. Must not be presented "
    "as a real conversation; record again on the real cubes (built without SYNTHETIC=1)."
)
_PROMPT_VERSION = re.compile(r"v[1-9][0-9]*")
# Shapes of the secrets this application handles (the model key, public API keys, private
# keys); none may appear in a recording.
_SECRET = re.compile(r"sk-ant-|\bvrk_[0-9a-f]+_|-----BEGIN")

ModelFactory = Callable[[Settings], ModelClient]


class SyntheticCubesError(RuntimeError):
    """A showcase region has no real cube."""


@dataclass(frozen=True)
class Recording:
    metadata: dict[str, object]
    events: tuple[AgentEvent, ...]
    workspace_id: str
    stopped: bool  # the cost limit refused a model call


def load_prompts(locale: Locale, path: Path = PROMPTS) -> list[str]:
    """The ordered user messages of `locale`."""
    prompts = yaml.safe_load(path.read_text(encoding="utf-8"))[locale]
    if not prompts or not all(isinstance(prompt, str) and prompt for prompt in prompts):
        raise ValueError(f"{path.name}: {locale} needs a list of non-empty messages")
    return list(prompts)


# The checks of a recording


def turns_of(events: Sequence[AgentEvent]) -> list[list[AgentEvent]]:
    """The events cut into turns, each starting at its `started`."""
    turns: list[list[AgentEvent]] = []
    for event in events:
        if isinstance(event, Started) or not turns:
            turns.append([])
        turns[-1].append(event)
    return turns


def recording_problems(
    metadata: Mapping[str, object],
    events: Sequence[AgentEvent],
    prompts: Sequence[str],
    locale: Locale,
    *,
    forbidden: Sequence[str] = (),
) -> list[str]:
    """Everything that keeps a recording from being the reviewed full flow; empty when none.

    `forbidden` holds strings the recording must not contain, such as the workspace id of the
    recording run. Whether the recording was made on real data is `not_real`.
    """
    problems = _metadata_problems(metadata, locale)
    turns = turns_of(events)
    users = [event.text for event in events if isinstance(event, UserMessage)]
    if users != list(prompts):
        problems.append(f"the user messages {users} are not the recorder prompts {list(prompts)}")
    results: list[Mapping[str, object]] = []
    for number, turn in enumerate(turns, start=1):
        problems += _turn_problems(number, turn, metadata.get("prompt_version"))
        results += [e.result for e in turn if isinstance(e, ToolFinished) and e.result is not None]
        answer = "".join(event.text for event in turn if isinstance(event, TextDelta))
        report = check_grounding(answer, results, users[:number], locale)
        if report.ungrounded:
            problems.append(f"turn {number}: figures without a source {list(report.ungrounded)}")
        if not answer.strip():
            problems.append(f"turn {number}: no answer")
        elif (language := classify_language(answer)) != locale:
            problems.append(f"turn {number}: the answer reads as {language}, not {locale}")

    finished = [event for event in events if isinstance(event, ToolFinished)]
    ran = [event.tool for event in finished if event.status == "ok"]
    position = 0
    for tool in FULL_FLOW:
        if tool not in ran[position:]:
            problems.append(f"{tool} did not succeed after {list(FULL_FLOW[:position]) or 'start'}")
            break
        position = ran.index(tool, position) + 1
    by_tool = {event.tool: event.result or {} for event in finished if event.status == "ok"}
    quote_id = by_tool.get("price_cover", {}).get("quote_id")
    approvals = [event for event in events if isinstance(event, ApprovalRequired)]
    if [approval.quote_id for approval in approvals] != [quote_id]:
        problems.append(f"expected one approval request for quote {quote_id}, got {approvals}")
    source = by_tool.get("get_weather_history", {}).get("source")
    if source != metadata.get("data_source"):
        problems.append(f"the history came from {source}, the metadata says otherwise")
    if flagged := [event.values for event in events if isinstance(event, GroundingFlagged)]:
        problems.append(f"grounding flags {flagged}")

    text = "\n".join(json.dumps(record(event), ensure_ascii=False) for event in events)
    text += json.dumps(dict(metadata), ensure_ascii=False)
    if _SECRET.search(text) or "workspace_id" in text:
        problems.append("the recording contains a secret or a workspace id")
    if any(value and value in text for value in forbidden):
        problems.append("the recording contains a forbidden value")
    return problems


def not_real(metadata: Mapping[str, object]) -> list[str]:
    """Why a recording is not one of the real model on the real cubes; empty when it is."""
    reasons = []
    if metadata.get("synthetic") is not False or metadata.get("data_source") != REAL_SOURCE:
        reasons.append(f"recorded on {metadata.get('data_source')} data, not the real cubes")
    if metadata.get("model") == SCRIPTED_MODEL:
        reasons.append("recorded with the scripted model client")
    return reasons


def _metadata_problems(metadata: Mapping[str, object], locale: Locale) -> list[str]:
    problems = []
    if "placeholder" in metadata:
        problems.append("the metadata marks a placeholder")
    if metadata.get("model") in (None, "", "none"):
        problems.append("the metadata names no model")
    if not _PROMPT_VERSION.fullmatch(str(metadata.get("prompt_version"))):
        problems.append(f"the prompt version {metadata.get('prompt_version')!r} is not v<N>")
    if metadata.get("locale") != locale:
        problems.append(f"the metadata locale {metadata.get('locale')!r} is not {locale}")
    if not metadata.get("recorded_on"):
        problems.append("the metadata has no date")
    source = metadata.get("data_source")
    if source not in DATA_SOURCES:
        problems.append(f"the data source {source!r} is not one of {list(DATA_SOURCES)}")
    synthetic = metadata.get("synthetic")
    if not isinstance(synthetic, bool) or (source == "synthetic" and not synthetic):
        problems.append("the metadata `synthetic` is missing or contradicts the data source")
    return problems


def _turn_problems(number: int, turn: Sequence[AgentEvent], prompt_version: object) -> list[str]:
    problems = []
    kinds = [type(event) for event in turn]
    if kinds[:2] != [Started, UserMessage] or kinds.count(UserMessage) != 1:
        problems.append(f"turn {number} does not open with started and one user_message")
    done = turn[-1]
    if not isinstance(done, Done):
        problems.append(f"turn {number} does not end with done")
    elif done.stop_reason != "end_turn" or done.prompt_version != prompt_version:
        problems.append(f"turn {number} ended {done.stop_reason} on {done.prompt_version}")
    if errors := [event.code for event in turn if isinstance(event, StreamError)]:
        problems.append(f"turn {number} has errors {errors}")
    return problems


# Recording


def record(event: AgentEvent) -> dict[str, object]:
    """One line of a recording file."""
    return {"event": EVENT_NAMES[type(event)], "data": event.model_dump(mode="json")}


def recording_text(metadata: Mapping[str, object], events: Sequence[AgentEvent]) -> str:
    lines = [json.dumps(dict(metadata), ensure_ascii=False)]
    lines += [json.dumps(record(event), ensure_ascii=False) for event in events]
    return "\n".join(lines) + "\n"


async def converse(
    locale: Locale,
    prompts: Sequence[str],
    spend: Spend,
    *,
    weather_root: Path,
    model_factory: ModelFactory,
    scripted: bool,
    allow_synthetic: bool,
) -> Recording:
    """The prompts through one conversation of a new visitor. Raises `SyntheticCubesError`
    before any model call when a showcase region has no real cube and that is not allowed."""

    def metered(settings: Settings) -> MeteredModel:
        return MeteredModel(model_factory(settings), spend)

    # The paid client, whatever the environment selects.
    overrides: dict[str, Any] = {} if scripted else {"assistant": {"model_client": "anthropic"}}
    with tempfile.TemporaryDirectory(prefix="veranico-replay-") as directory:
        async with application(
            Path(directory),
            weather_root,
            model_factory=metered,
            any_place_name=True,
            **overrides,
        ) as app:
            container, model = app.container, app.model_client
            if (
                container.access is None
                or container.assistant is None
                or container.climate is None
                or not isinstance(model, MeteredModel)
            ):
                raise RuntimeError("the application is not the API role with the metered model")
            synthetic = [
                r.region_id for r in await container.climate.facade.regions() if r.synthetic
            ]
            if synthetic and not allow_synthetic:
                raise SyntheticCubesError(
                    f"the cubes of {synthetic} under {weather_root} are synthetic or missing"
                )
            model.cost_of = container.access.facade.cost_of
            access, assistant = container.access.facade, container.assistant.facade
            principal, _ = await access.open_workspace(None)
            visitor = access.visitor(VISITOR_ADDRESS, None)

            events: list[AgentEvent] = []
            conversation_id: ConversationId | None = None
            for prompt in prompts:
                request = ChatRequest(
                    conversation_id=conversation_id, message=prompt, locale=locale
                )
                async for event in assistant.chat(principal, visitor, request):
                    events.append(event)
                    if isinstance(event, Started):
                        conversation_id = event.conversation_id
                        events.append(UserMessage(text=prompt))
                if spend.stopped:
                    break
            agent_model = app.settings.agent_model

    finished = [e for e in events if isinstance(e, ToolFinished) and e.status == "ok"]
    history = next((e.result for e in finished if e.tool == "get_weather_history"), None) or {}
    source = history.get("source", "none")
    done = next((e for e in reversed(events) if isinstance(e, Done)), None)
    metadata: dict[str, object] = {
        "prompt_version": done.prompt_version if done else "none",
        "model": SCRIPTED_MODEL if scripted else agent_model,
        "recorded_on": datetime.now(UTC).date().isoformat(),
        "locale": locale,
        "data_source": source,
        # A synthetic or missing cube of any showcase region, or a synthetic history.
        "synthetic": bool(synthetic) or source == "synthetic",
        "cube_checksum": _cube_checksum(weather_root, history.get("region_id")),
        "cost_usd": usd(spend.spent_usd_micros),
    }
    if metadata["synthetic"]:
        metadata["note"] = SYNTHETIC_NOTE
    return Recording(metadata, tuple(events), str(principal.workspace_id), spend.stopped)


def _cube_checksum(weather_root: Path, region_id: object) -> str | None:
    """The checksum of the cube manifest of the region the history came from."""
    if not isinstance(region_id, str):
        return None
    manifest = weather_root / "climate" / "cubes" / region_id / "manifest.json"
    try:
        checksum = json.loads(manifest.read_text(encoding="utf-8")).get("checksum")
    except (OSError, ValueError):
        return None
    return checksum if isinstance(checksum, str) else None


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(f".{path.name}.partial")
    partial.write_text(text, encoding="utf-8")
    partial.replace(path)


def cost_line(spend: Spend) -> str:
    used = spend.agent
    limit = f" (limit US$ {usd(spend.limit_usd_micros)})" if spend.limit_usd_micros else ""
    return (
        f"  {used.model_calls} model calls, input {used.input_tokens}, cache read "
        f"{used.cache_read_tokens}, cache write {used.cache_write_tokens}, output "
        f"{used.output_tokens}; cost of this run: US$ {usd(spend.spent_usd_micros)}{limit}"
        + (" - STOPPED BY THE COST LIMIT" if spend.stopped else "")
    )


def _arguments(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m tests.evals.record_replay",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--locale", required=True, choices=LOCALES)
    parser.add_argument(
        "--max-cost-usd",
        default=DEFAULT_MAX_COST_USD,
        help=f"hard stop for the cost of this run, in US dollars (default {DEFAULT_MAX_COST_USD})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="where to write the recording (default: the versioned fixture of the locale)",
    )
    parser.add_argument(
        "--weather-root",
        type=Path,
        help=f"the weather store with the cubes (default: {DEFAULT_WEATHER.relative_to(BACKEND)})",
    )
    parser.add_argument(
        "--allow-synthetic",
        action="store_true",
        help=(
            "record even though the cubes are synthetic; the metadata says `synthetic` and such "
            "a recording must not be presented as real (the fixture test rejects it)"
        ),
    )
    arguments = parser.parse_args(argv)
    try:
        arguments.max_cost_usd_micros = usd_micros(arguments.max_cost_usd)
    except ValueError as error:
        parser.error(str(error))
    return arguments


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    model_factory: ModelFactory | None = None,
    rejected: Path = REJECTED,
) -> int:
    """`model_factory` exists for the tests: it replaces the paid model, and the metadata then
    names the scripted model client."""
    arguments = _arguments(list(sys.argv[1:] if argv is None else argv))
    environ = os.environ if environ is None else environ
    locale: Locale = arguments.locale
    if model_factory is None and not environ.get(KEY_VARIABLE):
        print(
            f"record_replay: open, {KEY_VARIABLE} is not set: the recording needs the model API",
            file=sys.stderr,
        )
        return EXIT_OPEN
    try:
        prompts = load_prompts(locale)
        require_emulators()
    except (EmulatorDownError, ValueError) as error:
        print(f"record_replay: failed, {error}", file=sys.stderr)
        return EXIT_FAILED

    weather_root = arguments.weather_root or Path(
        environ.get("VERANICO_CLIMATE__STORE_ROOT") or DEFAULT_WEATHER
    )
    output = arguments.output or FIXTURES / f"{locale}.jsonl"
    spend = Spend(limit_usd_micros=arguments.max_cost_usd_micros)
    print(
        f"record_replay: {locale}, {len(prompts)} turns, weather {weather_root}, "
        f"cost limit US$ {usd(arguments.max_cost_usd_micros)}",
        flush=True,
    )
    try:
        recording = asyncio.run(
            converse(
                locale,
                prompts,
                spend,
                weather_root=weather_root,
                model_factory=model_factory or AnthropicModelClient.from_settings,
                scripted=model_factory is not None,
                allow_synthetic=arguments.allow_synthetic,
            )
        )
    except SyntheticCubesError as error:
        print(
            f"record_replay: refused, {error}. Build the real cubes (gate H1) first; "
            "--allow-synthetic records anyway, labelled synthetic, never to be shown as real.",
            file=sys.stderr,
        )
        return EXIT_REFUSED

    text = recording_text(recording.metadata, recording.events)
    metadata, events = parse_recording(text)  # the checks read what the file will hold
    problems = recording_problems(
        metadata, events, prompts, locale, forbidden=[recording.workspace_id]
    )
    if recording.stopped:
        problems.insert(0, "the cost limit stopped the run")
    print(cost_line(spend))
    if problems:
        kept = rejected / f"{locale}.rejected.jsonl"
        _write(kept, text)
        print(f"record_replay: failed, nothing written to {output}:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        print(f"  the recording is kept for reading at {kept}", file=sys.stderr)
        return EXIT_FAILED
    _write(output, text)
    for reason in not_real(metadata):
        print(f"  NOT REAL: {reason}; do not present this recording as real", file=sys.stderr)
    print(f"  recording: {output}; read it before committing it")
    return EXIT_WRITTEN


if __name__ == "__main__":
    sys.exit(main())
