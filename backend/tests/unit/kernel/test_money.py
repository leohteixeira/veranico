from typing import Literal

import pytest
from pydantic import TypeAdapter, ValidationError

from veranico.shared.kernel.money import Money, Rate

RATE = TypeAdapter(Rate)


def test_money_fields_are_the_contract() -> None:
    fields = Money.model_fields
    assert list(fields) == ["amount_cents", "currency"]
    assert fields["amount_cents"].annotation is int
    assert fields["amount_cents"].is_required()
    assert fields["currency"].annotation == Literal["BRL"]
    assert fields["currency"].default == "BRL"


def test_money_holds_integer_centavos_in_brl() -> None:
    money = Money(amount_cents=30_000_000)

    assert money.amount_cents == 30_000_000
    assert money.currency == "BRL"
    assert money.model_dump(mode="json") == {"amount_cents": 30_000_000, "currency": "BRL"}


@pytest.mark.parametrize("amount", [100.5, "100.5", "1e2", None])
def test_money_rejects_a_fractional_or_non_integer_amount(amount: object) -> None:
    with pytest.raises(ValidationError):
        Money.model_validate({"amount_cents": amount})


def test_money_rejects_another_currency() -> None:
    with pytest.raises(ValidationError):
        Money.model_validate({"amount_cents": 1, "currency": "USD"})


def test_money_is_frozen() -> None:
    money = Money(amount_cents=1)
    with pytest.raises(ValidationError):
        money.amount_cents = 2  # type: ignore[misc]  # the assignment is the behaviour under test


def test_money_has_no_arithmetic() -> None:
    a, b = Money(amount_cents=1), Money(amount_cents=2)
    for operation in ("__add__", "__sub__", "__mul__", "__truediv__", "__neg__", "__lt__"):
        assert operation not in vars(Money), operation
    with pytest.raises(TypeError):
        a + b  # type: ignore[operator]  # the unsupported operation is the behaviour under test


@pytest.mark.parametrize("value", ["0.123456", "-0.000001", "12.000000", "1.500000"])
def test_rate_accepts_six_decimal_places(value: str) -> None:
    assert RATE.validate_python(value) == value


@pytest.mark.parametrize(
    "value",
    ["0.12345", "0.1234567", "0", ".123456", "0,123456", "+0.123456", "1e-6", "0.123456\n", ""],
)
def test_rate_rejects_anything_else(value: str) -> None:
    with pytest.raises(ValidationError):
        RATE.validate_python(value)


def test_rate_rejects_a_number() -> None:
    with pytest.raises(ValidationError):
        RATE.validate_python(0.123456)
