"""Pure exact price-domain identities shared by formation and observation."""
from __future__ import annotations
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from typing import Any


class ShadowObservationRefused(RuntimeError):
    """The forward result cannot be labelled verified."""



def _positive_decimal(value: Any, *, where: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ShadowObservationRefused(f"{where} is not a decimal") from exc
    if not result.is_finite() or result <= 0:
        raise ShadowObservationRefused(
            f"{where} must be finite and positive")
    return result



def _decimal_text(value: Decimal) -> str:
    return format(value.normalize(), "f")



def _finite_decimal(value: Any, *, where: str) -> Decimal:
    if isinstance(value, bool):
        raise ShadowObservationRefused(f"{where} is not a finite decimal")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ShadowObservationRefused(
            f"{where} is not a finite decimal") from exc
    if not result.is_finite():
        raise ShadowObservationRefused(f"{where} is not a finite decimal")
    return result



def _optional_decimal_text(
        value: Any, *, where: str, positive: bool = False,
        nonnegative: bool = False) -> str | None:
    if value is None:
        return None
    result = _finite_decimal(value, where=where)
    if ((positive and result <= 0)
            or (nonnegative and result < 0)):
        raise ShadowObservationRefused(
            f"{where} is outside its economic price/quantity domain")
    return _decimal_text(result)



def _exact_price_ratio(value: Any, anchor: Any) -> list[str]:
    """An exact ratio of source decimals; never round a revised path to equal."""
    ratio = (Fraction(_positive_decimal(value, where="signal close"))
             / Fraction(_positive_decimal(anchor, where="signal basis close")))
    return [str(ratio.numerator), str(ratio.denominator)]



def _signal_price_identity(bar, anchor, *, warmup: bool = False) -> dict | None:
    """Bind a signal observation to its same-security source predecessor.

    Warmup supplies the first positive observation of the security's window.
    A genuinely new series has no predecessor and establishes its own basis.
    The canonical feed retains the owned absolute level for mixed precision.
    """
    if bar.signal_close is None:
        return None
    if anchor is None:
        return {"anchor": None,
                "ratio": _exact_price_ratio(bar.signal_close, bar.signal_close)}
    if (anchor.security_id != bar.security_id
            or anchor.session > bar.session
            or (not warmup and anchor.session == bar.session)):
        raise ShadowObservationRefused("signal basis anchor identity is invalid")
    return {
        "anchor": {
            "security_id": str(anchor.security_id), "ticker": str(anchor.ticker),
            "session": str(anchor.session),
            "raw_close": _optional_decimal_text(
                anchor.raw_close, where="signal basis raw close", positive=True),
        },
        "ratio": _exact_price_ratio(bar.signal_close, anchor.signal_close),
    }
