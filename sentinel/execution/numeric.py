"""Exact value identity for finite broker-facing Decimal quantities."""
from decimal import Context, Decimal, Inexact, localcontext
from fractions import Fraction


def exact_decimal(value: Fraction) -> Decimal:
    """Exactly render a sum/product of finite decimals, independently of context."""
    # Its reduced denominator contains only factors 2 and 5. Its bit length
    # bounds the terminating decimal scale; numerator digits plus that scale
    # bounds the required precision. Refuse any unexpected inexact conversion.
    precision = len(str(abs(value.numerator))) + value.denominator.bit_length()
    with localcontext(Context(prec=precision, traps=[Inexact])):
        return Decimal(value.numerator) / Decimal(value.denominator)


def decimal_text(value) -> str:
    number = Decimal(str(value))
    if not number.is_finite():
        raise ValueError("economic identity requires a finite Decimal")
    if number == 0:
        return "0"
    text = format(number, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text
