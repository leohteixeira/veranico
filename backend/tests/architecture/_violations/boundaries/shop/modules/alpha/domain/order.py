"""Breaks the layers: a domain importing a framework and its own application layer."""

from pydantic import BaseModel

from shop.modules.alpha.application.orders import available


class Order(BaseModel):
    quantity: int

    def fits(self) -> bool:
        return self.quantity <= available()
