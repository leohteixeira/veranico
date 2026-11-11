"""Deterministic compaction of the prompt (SPEC 9.2): summaries, order, thresholds."""

import copy
import json
from collections.abc import Mapping

import pytest

from tests.fakes.builders import backtest_result, priced_cover
from veranico.modules.assistant.domain.compaction import compact, estimate_tokens, summarise
from veranico.modules.assistant.domain.conversation import (
    AssistantStep,
    Entry,
    ToolCall,
    ToolResultEntry,
    UserEntry,
    is_valid_history,
)

pytestmark = [pytest.mark.req("R-9.2-3"), pytest.mark.req("R-9.2-2")]

CHARS_PER_TOKEN = 4
BACKTEST: dict[str, object] = backtest_result(seasons_excluded=[1951, 1987]).model_dump(mode="json")
PRICED: dict[str, object] = {
    "quote_id": "Q-7K3M9P",
    "priced": priced_cover(seasons_excluded=[1951]).model_dump(mode="json"),
}
DATASET = {"dataset_id": "point:86a8100c7ffffff", "first_year": 1950, "last_year": 2025}
ERROR = {"error_code": "invalid_cover", "message": "exit above trigger", "retryable": False}


def step(seq: int, turn: int, call_id: str, tool: str) -> AssistantStep:
    return AssistantStep(
        seq=seq,
        turn=turn,
        text="",
        tool_calls=(ToolCall(call_id=call_id, tool=tool, arguments={}),),
    )


def result(
    seq: int, turn: int, call_id: str, tool: str, payload: Mapping[str, object]
) -> ToolResultEntry:
    status = "error" if "error_code" in payload else "ok"
    return ToolResultEntry(
        seq=seq, turn=turn, call_id=call_id, tool=tool, status=status, result=payload
    )


def history() -> tuple[Entry, ...]:
    """Turn 1 backtests twice, turn 2 prices, turn 3 (current) backtests again."""
    return (
        UserEntry(seq=1, turn=1, text="Backtest it"),
        step(2, 1, "c1", "get_weather_history"),
        result(3, 1, "c1", "get_weather_history", DATASET),
        step(4, 1, "c2", "backtest_index"),
        result(5, 1, "c2", "backtest_index", BACKTEST),
        step(6, 1, "c3", "backtest_index"),
        result(7, 1, "c3", "backtest_index", BACKTEST),
        AssistantStep(seq=8, turn=1, text="It paid in some seasons."),
        UserEntry(seq=9, turn=2, text="Price it"),
        step(10, 2, "c4", "price_cover"),
        result(11, 2, "c4", "price_cover", PRICED),
        AssistantStep(seq=12, turn=2, text="Quote Q-7K3M9P."),
        UserEntry(seq=13, turn=3, text="And with another trigger?"),
        step(14, 3, "c5", "backtest_index"),
        result(15, 3, "c5", "backtest_index", BACKTEST),
    )


def tokens(entries: tuple[Entry, ...]) -> int:
    return estimate_tokens("", (), entries, CHARS_PER_TOKEN)


def compacted_seqs(entries: tuple[Entry, ...]) -> list[int]:
    return [
        entry.seq
        for entry in entries
        if isinstance(entry, ToolResultEntry) and entry.result.get("compacted") is True
    ]


def test_estimate_is_canonical_json_characters_over_the_divisor_rounded_up() -> None:
    entry = UserEntry(seq=1, turn=1, text="olá")
    fixed = len('{"system":"S","tools":[{"name":"t"}]}')
    chars = fixed + len('{"seq":1,"text":"olá","turn":1}')

    assert estimate_tokens("S", [{"name": "t"}], [entry], 4) == -(-chars // 4)
    assert estimate_tokens("S", [{"name": "t"}], [entry], 1) == chars
    assert estimate_tokens("S", [{"name": "t"}], [], 1) == fixed


def test_estimate_grows_with_the_system_prompt_and_the_tool_definitions() -> None:
    base = estimate_tokens("", (), history(), CHARS_PER_TOKEN)

    assert estimate_tokens("x" * 400, (), history(), CHARS_PER_TOKEN) == base + 100
    assert estimate_tokens("", [{"name": "x" * 400}], history(), CHARS_PER_TOKEN) > base + 100


def test_under_threshold_returns_entries_unchanged() -> None:
    entries = history()

    assert compact(entries, 3, tokens(entries), CHARS_PER_TOKEN) == entries


def test_over_threshold_replaces_oldest_result_first() -> None:
    entries = history()

    compacted = compact(entries, 3, tokens(entries) - 1, CHARS_PER_TOKEN)

    assert compacted_seqs(compacted) == [5]
    assert compacted[4] == result(
        5, 1, "c2", "backtest_index", summarise("backtest_index", BACKTEST)
    )


def test_stops_as_soon_as_estimate_fits() -> None:
    entries = history()
    one = compact(entries, 3, tokens(entries) - 1, CHARS_PER_TOKEN)

    # One token less than what one replacement achieves needs a second replacement, not a third.
    two = compact(entries, 3, tokens(one) - 1, CHARS_PER_TOKEN)

    assert compacted_seqs(two) == [5, 7]
    assert tokens(two) < tokens(one) < tokens(entries)


def test_system_prompt_and_tools_count_towards_the_threshold() -> None:
    entries = history()
    threshold = tokens(entries)

    assert compacted_seqs(compact(entries, 3, threshold, CHARS_PER_TOKEN)) == []
    assert compacted_seqs(compact(entries, 3, threshold, CHARS_PER_TOKEN, system="x" * 40)) == [5]
    with_tools = compact(entries, 3, threshold, CHARS_PER_TOKEN, tools=[{"name": "x" * 40}])
    assert compacted_seqs(with_tools) == [5]


def test_current_turn_results_are_never_replaced() -> None:
    entries = history()

    compacted = compact(entries, 3, 1, CHARS_PER_TOKEN)

    assert compacted_seqs(compacted) == [5, 7, 11]
    assert compacted[14] is entries[14]


def test_still_over_after_all_eligible_is_returned_as_is() -> None:
    entries = history()

    compacted = compact(entries, 3, 1, CHARS_PER_TOKEN)

    assert tokens(compacted) > 1
    assert len(compacted) == len(entries)


def test_small_results_and_error_results_are_kept_whole() -> None:
    entries = (
        UserEntry(seq=1, turn=1, text="go"),
        step(2, 1, "c1", "get_weather_history"),
        result(3, 1, "c1", "get_weather_history", DATASET),
        step(4, 1, "c2", "backtest_index"),
        result(5, 1, "c2", "backtest_index", ERROR),
        UserEntry(seq=6, turn=2, text="again"),
    )

    assert compact(entries, 2, 1, CHARS_PER_TOKEN) == entries
    assert summarise("get_weather_history", DATASET) is DATASET
    assert summarise("find_extreme_seasons", {"seasons": [1, 2]}) == {"seasons": [1, 2]}


def test_summary_keeps_quote_id_window_index_and_aggregates() -> None:
    priced = PRICED["priced"]
    assert isinstance(priced, dict)
    backtest = priced["backtest"]

    summary = summarise("price_cover", PRICED)

    assert summary["compacted"] is True
    assert summary["quote_id"] == "Q-7K3M9P"
    kept = summary["priced"]
    assert isinstance(kept, dict)
    assert kept["simulation"] == priced["simulation"]
    assert kept["premium"] == priced["premium"]
    assert kept["assumptions"] == priced["assumptions"]
    kept_backtest = kept["backtest"]
    assert kept_backtest["cover"] == backtest["cover"]
    assert kept_backtest["cover"]["index"]["window"] == backtest["cover"]["index"]["window"]
    assert kept_backtest["seasons_excluded_count"] == 1
    for key in (
        "dataset_id",
        "seasons_used",
        "trigger_frequency",
        "burn_cost",
        "max_payout",
        "max_payout_season",
        "trend",
        "warnings",
    ):
        assert kept_backtest[key] == backtest[key], key


def test_backtest_summary_keeps_the_cover_and_the_aggregates() -> None:
    summary = summarise("backtest_index", BACKTEST)

    assert summary == {
        "compacted": True,
        "dataset_id": BACKTEST["dataset_id"],
        "cover": BACKTEST["cover"],
        "seasons_used": BACKTEST["seasons_used"],
        "seasons_excluded_count": 2,
        "trigger_frequency": BACKTEST["trigger_frequency"],
        "burn_cost": BACKTEST["burn_cost"],
        "max_payout": BACKTEST["max_payout"],
        "max_payout_season": BACKTEST["max_payout_season"],
        "trend": BACKTEST["trend"],
        "warnings": BACKTEST["warnings"],
    }


def test_summary_drops_per_season_list() -> None:
    backtest = summarise("backtest_index", BACKTEST)
    priced = summarise("price_cover", PRICED)

    assert "seasons" not in backtest
    assert "seasons_excluded" not in backtest
    kept = priced["priced"]
    assert isinstance(kept, dict)
    # The list of excluded years survives only as a parameter of its warning, which is kept.
    assert "seasons" not in kept["backtest"]
    assert "seasons_excluded" not in kept["backtest"]
    assert len(json.dumps(priced)) < len(json.dumps(PRICED)) // 2
    assert len(json.dumps(backtest)) < len(json.dumps(BACKTEST)) // 2


def test_summary_of_a_summary_is_itself() -> None:
    summary = summarise("backtest_index", BACKTEST)

    assert summarise("backtest_index", summary) is summary


def test_call_ids_and_order_are_preserved() -> None:
    entries = history()

    compacted = compact(entries, 3, 1, CHARS_PER_TOKEN)

    assert [entry.seq for entry in compacted] == [entry.seq for entry in entries]
    assert [type(entry) for entry in compacted] == [type(entry) for entry in entries]
    assert [e.call_id for e in compacted if isinstance(e, ToolResultEntry)] == [
        e.call_id for e in entries if isinstance(e, ToolResultEntry)
    ]
    assert is_valid_history(compacted)


def test_input_entries_are_not_mutated() -> None:
    entries = history()
    before = copy.deepcopy(entries)

    compact(entries, 3, 1, CHARS_PER_TOKEN)

    assert entries == before
    assert "seasons" in BACKTEST


def test_compaction_is_deterministic_and_idempotent() -> None:
    threshold = tokens(history()) - 1

    first = compact(history(), 3, threshold, CHARS_PER_TOKEN)
    second = compact(history(), 3, threshold, CHARS_PER_TOKEN)

    assert first == second
    assert compact(first, 3, threshold, CHARS_PER_TOKEN) == first
    everything = compact(history(), 3, 1, CHARS_PER_TOKEN)
    assert compact(everything, 3, 1, CHARS_PER_TOKEN) == everything
