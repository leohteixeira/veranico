"""Deterministic prompt compaction (SPEC 9.2). Code, not the model, shortens the prompt.

* Estimate. The characters of the canonical JSON (sorted keys, no whitespace) of the system
  prompt with the tool definitions, plus those of every entry, divided by `chars_per_token`
  and rounded up. It is an estimate, not a tokenizer.
* When. Before every model call, from the stored history. Nothing about compaction is stored.
* What. While the estimate exceeds the threshold, the oldest tool result not yet replaced
  (ascending `seq`) is replaced by `summarise(...)`; it stops as soon as the estimate fits.
  Results of the current turn are never replaced, because the model still has to cite them.
  If the estimate still exceeds the threshold when every eligible result is replaced, the
  entries are returned as they are then: the per-conversation token budget is the bound.
* Summary. `{"compacted": true, ...}`. `backtest_index` keeps the dataset, the cover (index
  definition with its window, limit), `seasons_used`, the count of excluded seasons,
  `trigger_frequency`, `burn_cost`, `max_payout`, `max_payout_season`, `trend` and `warnings`.
  `price_cover` keeps the `quote_id`, the same backtest aggregates, the simulation, the premium
  and the assumptions. Both drop the per-season list. The other tools' results and error
  results are already small and are kept whole.
* Invariants. Call identifiers and the order of entries never change. The input entries are
  never modified. The same history and settings give a byte-identical prompt.
"""

import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, replace

from veranico.modules.assistant.domain.conversation import Entry, ToolResultEntry

_BACKTEST_KEPT = (
    "dataset_id",
    "cover",
    "seasons_used",
    "trigger_frequency",
    "burn_cost",
    "max_payout",
    "max_payout_season",
    "trend",
    "warnings",
)
_PRICED_KEPT = ("simulation", "premium", "assumptions")


def summarise(tool: str, result: Mapping[str, object]) -> Mapping[str, object]:
    """The structured summary that stands for a stored tool result in the prompt."""
    if result.get("compacted") is True:
        return result
    if tool == "backtest_index":
        return {"compacted": True, **_backtest_summary(result)}
    if tool == "price_cover":
        summary: dict[str, object] = {"compacted": True}
        if "quote_id" in result:
            summary["quote_id"] = result["quote_id"]
        priced = result.get("priced")
        if isinstance(priced, Mapping):
            kept: dict[str, object] = {}
            backtest = priced.get("backtest")
            if isinstance(backtest, Mapping):
                kept["backtest"] = _backtest_summary(backtest)
            kept.update({key: priced[key] for key in _PRICED_KEPT if key in priced})
            summary["priced"] = kept
        return summary
    return result


def _backtest_summary(backtest: Mapping[str, object]) -> dict[str, object]:
    summary: dict[str, object] = {key: backtest[key] for key in _BACKTEST_KEPT if key in backtest}
    excluded = backtest.get("seasons_excluded")
    if isinstance(excluded, list | tuple):
        summary["seasons_excluded_count"] = len(excluded)
    return summary


def estimate_tokens(
    system: str,
    tools: Sequence[Mapping[str, object]],
    entries: Sequence[Entry],
    chars_per_token: int,
) -> int:
    """Estimated prompt size in tokens: canonical JSON characters over `chars_per_token`."""
    chars = _fixed_chars(system, tools) + sum(_entry_chars(entry) for entry in entries)
    return _tokens(chars, chars_per_token)


def compact(
    entries: Sequence[Entry],
    current_turn: int,
    threshold: int,
    chars_per_token: int,
    *,
    system: str = "",
    tools: Sequence[Mapping[str, object]] = (),
) -> tuple[Entry, ...]:
    """The entries to put in the prompt: the input, with the oldest results summarised if needed."""
    compacted = list(entries)
    chars = _fixed_chars(system, tools) + sum(_entry_chars(entry) for entry in compacted)
    oldest_first = sorted(range(len(compacted)), key=lambda position: compacted[position].seq)
    for position in oldest_first:
        if _tokens(chars, chars_per_token) <= threshold:
            break
        entry = compacted[position]
        if (
            not isinstance(entry, ToolResultEntry)
            or entry.turn == current_turn
            or entry.status != "ok"
        ):
            continue
        summary = summarise(entry.tool, entry.result)
        if summary is entry.result:
            continue
        shortened = replace(entry, result=summary)
        chars += _entry_chars(shortened) - _entry_chars(entry)
        compacted[position] = shortened
    return tuple(compacted)


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _fixed_chars(system: str, tools: Sequence[Mapping[str, object]]) -> int:
    return len(_canonical({"system": system, "tools": list(tools)}))


def _entry_chars(entry: Entry) -> int:
    return len(_canonical(asdict(entry)))


def _tokens(chars: int, chars_per_token: int) -> int:
    return -(-chars // chars_per_token)
