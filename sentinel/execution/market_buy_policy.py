"""Explicit whole-share market BUY policy for backed owner PAPER."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
import os
from typing import Mapping

from sentinel.execution.numeric import exact_decimal
from sentinel.execution.target_reprojection import TargetProjectionRefused


MARKET_MODE = "MARKET_DAY_V1"
MARKET_BUY_BUFFER_BPS = 100
MARKET_BUY_HEADROOM = Decimal("1.00")


@dataclass(frozen=True)
class MarketBuyPolicy:
    @classmethod
    def from_env(cls, values: Mapping[str, str] | None = None) -> MarketBuyPolicy | None:
        values = os.environ if values is None else values
        if values.get("SENTINEL_PAPER_BUY_POLICY", "").strip() != MARKET_MODE:
            return None
        if values.get("SENTINEL_PAPER_BUY_CAP_BPS", "").strip():
            raise TargetProjectionRefused("market DAY BUY policy cannot select a protected BUY cap")
        if values.get("SENTINEL_PAPER_DEBUG_WINDOW", "").strip():
            raise TargetProjectionRefused("market DAY BUY policy cannot select the protected debug window")

        from sentinel import local_paper
        from sentinel.config import DEFAULT_BASE_URL

        if values.get("ALPACA_BASE_URL", DEFAULT_BASE_URL) != DEFAULT_BASE_URL:
            raise TargetProjectionRefused("market DAY BUY policy requires the Alpaca PAPER endpoint")
        try:
            backed_owner_paper = (
                local_paper.enabled(values)
                and local_paper.backup_policy(values) == local_paper.BACKUP_POLICY)
        except RuntimeError as exc:
            raise TargetProjectionRefused("market DAY BUY policy requires backed owner PAPER") from exc
        if not backed_owner_paper:
            raise TargetProjectionRefused("market DAY BUY policy requires backed owner PAPER")
        return cls()

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": "sentinel.market-buy-policy/1",
            "profile": MARKET_MODE,
            "reference_recipe": "FRESH_IEX_BID_ASK_V1",
            "quantity_rounding": "WHOLE_SHARES_DOWN",
            "order_type": "market",
            "time_in_force": "day",
            "order_class": "simple",
            "extended_hours": False,
            "start_delay_seconds": 60,
            "new_submit_cutoff_seconds": 600,
            "sizing_buffer_bps": MARKET_BUY_BUFFER_BPS,
            "buy_cash_headroom": str(MARKET_BUY_HEADROOM),
            "max_unresolved_buys": 1,
        }

    @classmethod
    def from_dict(cls, raw: object) -> MarketBuyPolicy:
        policy = cls()
        expected = policy.to_dict()
        if (not isinstance(raw, dict) or raw != expected
                or any(type(raw[key]) is not type(value) for key, value in expected.items())):
            raise TargetProjectionRefused("market DAY BUY policy terms are unsupported")
        return policy

    def fingerprint(self) -> str:
        from sentinel.authority.canonical import canonical_sha256
        return canonical_sha256(self.to_dict())


def estimated_market_buy_cost(quantity: Decimal, ask: Decimal) -> Decimal:
    """Calculate the cash estimate for a positive whole-share buy."""
    if (not isinstance(quantity, Decimal) or not quantity.is_finite()
            or quantity <= 0 or quantity != quantity.to_integral_value()):
        raise TargetProjectionRefused("market BUY quantity must be positive whole shares")
    if not isinstance(ask, Decimal) or not ask.is_finite() or ask <= 0:
        raise TargetProjectionRefused("market BUY ask must be a positive finite Decimal")
    buffer = Fraction(10_000 + MARKET_BUY_BUFFER_BPS, 10_000)
    return exact_decimal(Fraction(quantity) * Fraction(ask) * buffer + Fraction(MARKET_BUY_HEADROOM))
