import re

import pytest

from tests.fakes import builders
from veranico.modules.pricing.contracts import SimulationOptions
from veranico.modules.quoting.contracts import CreateQuote, QuoteLocationInput
from veranico.modules.quoting.domain.fingerprint import fingerprint

pytestmark = pytest.mark.req("R-6-4")

BASE: dict[str, object] = {
    "location": {"lat": -12.55, "lon": -55.72, "label": "Fazenda", "admin_region": "MT"},
    "cover": {
        "index": {
            "index_type": "rainfall_below",
            "window": {"start": "10-01", "end": "03-31"},
            "trigger": 600.0,
            "exit": 300.0,
        },
        "limit": {"amount_cents": 10_000_000, "currency": "BRL"},
    },
    "simulation": {"n": 100_000, "seed": 42},
}


def _changed(path: tuple[str, ...], value: object) -> CreateQuote:
    """The base command with one field replaced."""

    def replace(node: dict[str, object], keys: tuple[str, ...]) -> dict[str, object]:
        head, *rest = keys
        child = node[head]
        if not rest:
            return {**node, head: value}
        assert isinstance(child, dict)
        return {**node, head: replace(child, tuple(rest))}

    return CreateQuote.model_validate(replace(BASE, path))


def test_equal_commands_give_equal_fingerprints() -> None:
    first = CreateQuote.model_validate(BASE)
    second = CreateQuote(
        location=QuoteLocationInput(lat=-12.55, lon=-55.72, label="Fazenda", admin_region="MT"),
        cover=builders.cover(),
        simulation=SimulationOptions(n=100_000, seed=42),
    )

    assert first == second
    assert fingerprint(first) == fingerprint(second)
    assert re.fullmatch(r"[0-9a-f]{64}", fingerprint(first))


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("location", "lat"), -12.56),
        (("location", "lon"), -55.73),
        (("location", "label"), "Outra fazenda"),
        (("location", "label"), None),
        (("location", "admin_region"), "GO"),
        (("location", "admin_region"), None),
        (("cover", "index", "index_type"), "dry_spell_above"),
        (("cover", "index", "window", "start"), "10-02"),
        (("cover", "index", "window", "end"), "03-30"),
        (("cover", "index", "trigger"), 600.1),
        (("cover", "index", "exit"), 299.9),
        (("cover", "limit", "amount_cents"), 10_000_001),
        (("simulation", "n"), 99_999),
        (("simulation", "seed"), 43),
    ],
)
def test_a_change_in_any_field_changes_the_fingerprint(
    path: tuple[str, ...], value: object
) -> None:
    assert fingerprint(_changed(path, value)) != fingerprint(CreateQuote.model_validate(BASE))


def test_an_explicit_default_equals_an_omitted_one() -> None:
    cover = builders.cover()
    omitted = CreateQuote(location=QuoteLocationInput(lat=-12.55, lon=-55.72), cover=cover)
    explicit = CreateQuote(
        location=QuoteLocationInput(lat=-12.55, lon=-55.72, label=None, admin_region=None),
        cover=cover,
        simulation=SimulationOptions(),
    )
    from_json = CreateQuote.model_validate(
        {"location": {"lat": -12.55, "lon": -55.72}, "cover": cover.model_dump(mode="json")}
    )

    assert fingerprint(omitted) == fingerprint(explicit) == fingerprint(from_json)
