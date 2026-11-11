"""The `Makefile` loads an environment file for its recipes.

The loader is pointed at a temporary file through `ENV_FILE`; the real `.env` is never opened.
A second makefile, written by the test, adds the one recipe that reveals chosen variables: the
real `Makefile` has no recipe that prints the environment.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
MAKEFILE = REPO / "Makefile"

NAMES = ("PLAIN", "JSON_VALUE", "DOLLAR", "EMPTY", "FROM_SHELL", "OVERRIDDEN", "NOT_IN_FILE")
_SHOW = 'eval "value=\\$${$$name-<unset>}"; printf \'%s=%s\\n\' "$$name" "$$value"'
PROBE = f"probe:\n\t@for name in {' '.join(NAMES)}; do {_SHOW}; done\n"

pytestmark = pytest.mark.skipif(shutil.which("make") is None, reason="GNU Make is not installed")


def _recipe_environment(
    tmp_path: Path, env_file: Path, shell: dict[str, str] | None = None
) -> dict[str, str]:
    """What a recipe sees for each probed name, with `ENV_FILE` pointing at `env_file`."""
    probe = tmp_path / "probe.mk"
    probe.write_text(PROBE, encoding="utf-8")
    environment = {"PATH": os.environ["PATH"], **(shell or {})}
    done = subprocess.run(
        ["make", "-f", str(MAKEFILE), "-f", str(probe), f"ENV_FILE={env_file}", "probe"],
        cwd=tmp_path,  # no `.env` here, and the real one is not the default of this run
        env=environment,
        capture_output=True,
        text=True,
        check=True,
    )
    return dict(line.split("=", 1) for line in done.stdout.splitlines())


def test_values_reach_a_recipe_verbatim(tmp_path: Path) -> None:
    env_file = tmp_path / "values"
    env_file.write_text(
        "# a comment\n"
        "PLAIN=hello world\n"
        'JSON_VALUE={"model": {"input": 100000, "output": 500000}, "list": ["http://x:1"]}\n'
        "DOLLAR=pa$$word$HOME$(shell echo expanded)\n",
        encoding="utf-8",
    )

    seen = _recipe_environment(tmp_path, env_file)

    assert seen["PLAIN"] == "hello world"
    assert seen["JSON_VALUE"] == (
        '{"model": {"input": 100000, "output": 500000}, "list": ["http://x:1"]}'
    )
    assert seen["DOLLAR"] == "pa$$word$HOME$(shell echo expanded)"


def test_one_pair_of_quotes_around_a_one_word_value_is_dropped(tmp_path: Path) -> None:
    env_file = tmp_path / "values"
    env_file.write_text(
        'PLAIN="sk-quoted-value"\n'
        "JSON_VALUE='single-quoted'\n"
        'DOLLAR="pa$$word$HOME"\n'
        'EMPTY=""\n'
        'OVERRIDDEN="two words"\n',
        encoding="utf-8",
    )

    seen = _recipe_environment(tmp_path, env_file)

    assert seen["PLAIN"] == "sk-quoted-value"
    assert seen["JSON_VALUE"] == "single-quoted"
    assert seen["DOLLAR"] == "pa$$word$HOME"
    assert seen["EMPTY"] == "<unset>"
    assert seen["OVERRIDDEN"] == '"two words"'


def test_a_name_left_empty_is_unset_for_the_recipe(tmp_path: Path) -> None:
    """An empty value must not replace a default or a generated development secret."""
    env_file = tmp_path / "values"
    env_file.write_text("EMPTY=\nPLAIN=set\n", encoding="utf-8")

    seen = _recipe_environment(tmp_path, env_file)

    assert seen["EMPTY"] == "<unset>"
    assert seen["PLAIN"] == "set"


def test_a_value_in_the_file_wins_over_the_calling_shell(tmp_path: Path) -> None:
    env_file = tmp_path / "values"
    env_file.write_text("OVERRIDDEN=from-file\n", encoding="utf-8")

    seen = _recipe_environment(
        tmp_path, env_file, shell={"OVERRIDDEN": "from-shell", "NOT_IN_FILE": "from-shell"}
    )

    assert seen["OVERRIDDEN"] == "from-file"
    assert seen["NOT_IN_FILE"] == "from-shell"


def test_an_empty_name_in_the_file_also_unsets_the_value_of_the_calling_shell(
    tmp_path: Path,
) -> None:
    env_file = tmp_path / "values"
    env_file.write_text("FROM_SHELL=\n", encoding="utf-8")

    seen = _recipe_environment(tmp_path, env_file, shell={"FROM_SHELL": "from-shell"})

    assert seen["FROM_SHELL"] == "<unset>"


def test_a_missing_file_is_not_an_error(tmp_path: Path) -> None:
    seen = _recipe_environment(tmp_path, tmp_path / "absent")

    assert set(seen.values()) == {"<unset>"}


def test_no_recipe_prints_the_environment() -> None:
    """`env`, `printenv`, `export -p` or `set` in a recipe would print the loaded keys."""
    recipe_lines = [
        line.strip()
        for line in MAKEFILE.read_text(encoding="utf-8").splitlines()
        if line.startswith("\t")
    ]
    for line in recipe_lines:
        words = line.replace(";", " ").replace("(", " ").replace("|", " ").split()
        assert "printenv" not in words, line
        assert "env" not in words, line
        assert "export -p" not in line, line
        assert "declare -p" not in line, line


def test_no_provider_key_reaches_a_test_process() -> None:
    """`tests/conftest.py` drops the keys the Makefile exports, so no test can spend money."""
    assert "ANTHROPIC_API_KEY" not in os.environ
    assert "CDS_API_KEY" not in os.environ
