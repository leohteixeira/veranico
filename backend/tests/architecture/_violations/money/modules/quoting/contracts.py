"""Breaks the money rules: money fields typed `float`."""

from pydantic import BaseModel


class Money(BaseModel, frozen=True):
    amount_cents: float


class Priced(BaseModel, frozen=True):
    premium: float
    limit: float | None
    payout_1_in_10: "float"
    burn_cost: float
    expected_loss: float
    std_dev: float
    gap_to_burn_cost: float
    index_value: float  # a physical quantity: allowed
    seasons_used: int
