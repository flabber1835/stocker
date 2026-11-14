"""Requested dollars and acquired shares are different units."""
from __future__ import annotations

from decimal import Decimal
from fractions import Fraction

from pydantic import BaseModel, ConfigDict, model_validator


class OrderAmount(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    quantity: Decimal | None = None
    notional: Decimal | None = None

    @model_validator(mode="after")
    def exclusive_positive_amount(self) -> OrderAmount:
        if (self.quantity is None) == (self.notional is None):
            raise ValueError("exactly one of quantity and notional is required")
        value = self.quantity if self.quantity is not None else self.notional
        if not value.is_finite() or value <= 0:
            raise ValueError("order amount must be finite and positive")
        return self

    def require_notional_buy(self, side, terms) -> None:
        if self.notional is not None and (
                side.value != "BUY" or terms is None
                or terms.order_type != "market" or terms.time_in_force != "day"
                or terms.order_class != "simple" or terms.extended_hours):
            raise ValueError("owned notional orders require simple regular-session MARKET/DAY BUY")

    def require_wire_precision(self) -> None:
        value, increment = ((self.quantity, Decimal("0.000000001"))
                            if self.quantity is not None else
                            (self.notional, Decimal("0.01")))
        if (Fraction(value) / Fraction(increment)).denominator != 1:
            raise ValueError("order amount exceeds broker decimal precision")

    def wire(self) -> dict[str, str]:
        self.require_wire_precision()
        return ({"qty": str(self.quantity)} if self.quantity is not None
                else {"notional": str(self.notional)})


def optional_decimal_text(value: Decimal | None) -> str | None:
    return None if value is None else str(value)
