"""The replay recorder's refusals and its input that need no emulator and no model."""

from pathlib import Path

import pytest

from tests.evals import record_replay
from tests.evals.record_replay import EXIT_OPEN, load_prompts
from veranico.modules.assistant.application.replay import LOCALES
from veranico.shared.kernel.ids import Locale


def test_a_missing_key_is_refused_before_anything_runs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output = tmp_path / "en.jsonl"

    code = record_replay.main(
        ["--locale", "en", "--output", str(output)], environ={}, rejected=tmp_path / "rejected"
    )

    assert code == EXIT_OPEN
    assert "ANTHROPIC_API_KEY is not set" in capsys.readouterr().err
    assert not output.exists()
    assert not (tmp_path / "rejected").exists()


def test_the_cost_limit_must_be_a_positive_amount(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as raised:
        record_replay.main(
            ["--locale", "en", "--max-cost-usd", "0", "--output", str(tmp_path / "en.jsonl")],
            environ={},
        )

    assert raised.value.code == 2


@pytest.mark.parametrize("locale", LOCALES)
def test_each_locale_asks_for_the_whole_flow_in_four_turns(locale: Locale) -> None:
    prompts = load_prompts(locale)

    assert len(prompts) == 4
    assert "Três Pontas" in prompts[0]
    assert "Seguradora Jatobá" in prompts[-1]
