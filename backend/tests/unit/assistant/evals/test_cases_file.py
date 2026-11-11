"""The cases file of the evaluation suite."""

import re
from pathlib import Path

import pytest
import yaml

from tests.evals.cases import CasesFileError, load_cases, select
from tests.evals.checks import CHECKS

REQUIREMENTS = Path(__file__).parents[3] / "requirements.yaml"
NAMED_CASES = {
    "happy_full_flow_sul_de_minas",
    "happy_full_flow_sorriso",
    "happy_full_flow_ribeirao_preto",
    "happy_dry_spell_index",
    "happy_window_crossing_year_end",
    "happy_term_sheet_then_submission",
    "happy_full_flow_portuguese",
    "clarify_missing_limit",
    "clarify_missing_window",
    "clarify_ambiguous_place_name",
    "grounding_rough_premium_before_pricing",
    "grounding_compare_two_triggers",
    "grounding_one_in_100_payout",
    "guardrail_approve_own_submission",
    "guardrail_guaranteed_payout",
    "guardrail_injection_in_place_name",
    "guardrail_location_without_data",
    "guardrail_out_of_scope_stock_prices",
}


@pytest.mark.req("R-16.6-1")
def test_cases_file_has_the_18_named_cases_with_known_checks() -> None:
    cases = load_cases()

    assert len(cases) == 18
    assert {case.id for case in cases} == NAMED_CASES
    for case in cases:
        assert set(case.checks) <= set(CHECKS), case.id
        assert case.checks["answers_in"] == case.locale, case.id
        assert len(case.checks) > 1, case.id  # something beyond the language
        assert all(case.turns), case.id
    assert {case.locale for case in cases} == {"en", "pt-BR"}


@pytest.mark.req("R-16.6-1")
def test_every_case_names_its_requirements() -> None:
    document = yaml.safe_load(REQUIREMENTS.read_text(encoding="utf-8"))
    known = {entry["id"] for entry in document["requirements"]}

    for case in load_cases():
        assert case.req, case.id
        assert set(case.req) <= known, case.id


def test_every_refusal_says_what_was_asked_and_every_claim_is_a_valid_pattern() -> None:
    for case in load_cases():
        refusal = case.checks.get("refuses")
        if refusal is not None:
            assert refusal["asked"].strip(), case.id
        claims = [
            *(refusal or {}).get("forbidden_claims", []),
            *case.checks.get("must_not_claim", []),
        ]
        for claim in claims:
            re.compile(claim)


def test_the_injected_place_name_is_expected_whole_as_the_query() -> None:
    (case,) = select(load_cases(), ["guardrail_injection_in_place_name"])
    (constraint,) = case.checks["tool_args"]

    assert constraint["tool"] == "resolve_location"
    assert f'"{constraint["args"]["query"]}"' in case.turns[0]


def test_a_selection_keeps_the_order_of_the_file_and_rejects_unknown_names() -> None:
    cases = load_cases()

    chosen = select(cases, ["clarify_missing_limit", "happy_full_flow_sul_de_minas"])

    assert [case.id for case in chosen] == ["happy_full_flow_sul_de_minas", "clarify_missing_limit"]
    assert select(cases, None) == cases
    with pytest.raises(CasesFileError, match="no_such_case"):
        select(cases, ["no_such_case"])


@pytest.mark.parametrize(
    ("entry", "problem"),
    [
        ({"id": "a", "locale": "fr", "turns": ["x"], "checks": {"must_clarify": True}}, "locale"),
        ({"id": "a", "locale": "en", "turns": [], "checks": {"must_clarify": True}}, "turn"),
        ({"id": "a", "locale": "en", "turns": ["x"], "checks": {"is_nice": True}}, "is_nice"),
        ({"id": "a", "locale": "en", "turns": ["x"], "checks": {}}, "no check"),
        ({"id": "a", "locale": "en", "turns": ["x"], "checks": {"answers_in": "en"}}, "answers_in"),
        (
            {"id": "a", "locale": "en", "turns": ["x"], "checks": {"must_clarify": True}},
            "requirement",
        ),
    ],
)
def test_a_malformed_case_is_rejected(
    tmp_path: Path, entry: dict[str, object], problem: str
) -> None:
    path = tmp_path / "cases.yaml"
    path.write_text(yaml.safe_dump({"cases": [entry]}), encoding="utf-8")

    with pytest.raises(CasesFileError, match=problem):
        load_cases(path)
