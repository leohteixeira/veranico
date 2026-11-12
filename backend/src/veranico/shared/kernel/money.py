"""Money and rates as they cross module boundaries.

`Money` has no arithmetic: only `pricing/domain` computes monetary values. `format_money` lays
out the digits of the integer centavos for a locale by string operations only, so the term
sheet and the assistant show one amount the same way.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, StringConstraints

from veranico.shared.kernel.ids import Locale

Rate = Annotated[str, StringConstraints(pattern=r"^-?\d+\.\d{6}$")]


class Money(BaseModel, frozen=True):
    amount_cents: int
    currency: Literal["BRL"] = "BRL"


_MONEY_SEPARATORS: dict[str, tuple[str, str]] = {  # locale: (decimal mark, thousands mark)
    "en": (".", ","),
    "pt-BR": (",", "."),
}


def format_money(amount_cents: int, locale: Locale) -> str:
    """`123456` → `R$ 1,234.56` (`en`) or `R$ 1.234,56` (`pt-BR`); a leading minus when negative.

    A malformed input raises `ValueError`: a formatter never guesses.
    """
    if type(amount_cents) is not int:
        raise ValueError("money is an integer number of centavos")
    try:
        decimal, thousands = _MONEY_SEPARATORS[locale]
    except KeyError:
        raise ValueError(f"unsupported locale: {locale!r}") from None
    digits = str(amount_cents)
    sign = "-" if digits.startswith("-") else ""
    digits = digits.removeprefix("-").zfill(3)
    whole, centavos = digits[:-2], digits[-2:]
    groups = []
    while whole:
        groups.append(whole[-3:])
        whole = whole[:-3]
    return f"{sign}R$ {thousands.join(reversed(groups))}{decimal}{centavos}"
