"""Money and rates as they cross module boundaries.

`Money` has no arithmetic: only `pricing/domain` computes monetary values.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, StringConstraints

Rate = Annotated[str, StringConstraints(pattern=r"^-?\d+\.\d{6}$")]


class Money(BaseModel, frozen=True):
    amount_cents: int
    currency: Literal["BRL"] = "BRL"
