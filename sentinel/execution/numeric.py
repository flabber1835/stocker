"""Exact value identity for finite broker-facing Decimal quantities."""
from decimal import Decimal


def decimal_text(value) -> str:
    number = Decimal(str(value))
    if not number.is_finite():
        raise ValueError("economic identity requires a finite Decimal")
    if number == 0:
        return "0"
    text = format(number, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text
