"""Typed execution-only evidence for the first regular-session raw open."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from types import MappingProxyType
from typing import Mapping

from sentinel.feed import calendar

SOURCE = "ALPACA_SIP_RAW_OPENING_MINUTE_V1"
ENDPOINT = "https://data.alpaca.markets/v2/stocks/bars"


class OpeningPriceUnavailable(RuntimeError):
    """The opening evidence is incomplete or unavailable for this attempt."""


@dataclass(frozen=True)
class OpeningPrices:
    session: date
    opening_at: datetime
    observed_at: datetime
    prices: Mapping[str, Decimal]
    symbols: Mapping[str, str]
    broker_ids: Mapping[str, str]
    source: str = SOURCE

    def __post_init__(self):
        opened, closed = calendar.session_window(self.session)
        if (self.source != SOURCE or self.opening_at != opened
                or self.observed_at.tzinfo is None
                or not opened + timedelta(minutes=1) <= self.observed_at < closed):
            raise OpeningPriceUnavailable("opening prices have invalid source or session timestamps")
        if (not self.prices or set(self.prices) != set(self.symbols)
                or any(not isinstance(sid, str) or not sid for sid in self.prices)
                or len(set(self.symbols.values())) != len(self.symbols)
                or any(not isinstance(symbol, str) or not symbol for symbol in self.symbols.values())):
            raise OpeningPriceUnavailable("opening prices have incomplete or ambiguous identities")
        if (set(self.broker_ids) != set(self.prices)
                or any(not isinstance(asset, str) or not asset.strip()
                       for asset in self.broker_ids.values())
                or len(set(self.broker_ids.values())) != len(self.broker_ids)):
            raise OpeningPriceUnavailable("opening prices require unique stable broker asset identities")
        if any(not isinstance(p, Decimal) or not p.is_finite() or p <= 0
               for p in self.prices.values()):
            raise OpeningPriceUnavailable("opening prices must be positive finite Decimal")
        object.__setattr__(self, "prices", MappingProxyType(dict(self.prices)))
        object.__setattr__(self, "symbols", MappingProxyType(dict(self.symbols)))
        object.__setattr__(self, "broker_ids", MappingProxyType(dict(self.broker_ids)))

    def to_dict(self):
        return {"source": self.source, "session": self.session.isoformat(),
                "opening_at": self.opening_at.isoformat(),
                "observed_at": self.observed_at.isoformat(),
                "prices": {sid: str(p) for sid, p in sorted(self.prices.items())},
                "symbols": dict(sorted(self.symbols.items())),
                "broker_ids": dict(sorted(self.broker_ids.items()))}

    @classmethod
    def from_dict(cls, raw):
        if not isinstance(raw, dict) or set(raw) != {
                "source", "session", "opening_at", "observed_at", "prices", "symbols", "broker_ids"}:
            raise OpeningPriceUnavailable("invalid opening price evidence shape")
        try:
            return cls(date.fromisoformat(raw["session"]),
                datetime.fromisoformat(raw["opening_at"]), datetime.fromisoformat(raw["observed_at"]),
                {sid: Decimal(p) for sid, p in raw["prices"].items()}, raw["symbols"],
                raw["broker_ids"], raw["source"])
        except (TypeError, ValueError, ArithmeticError, AttributeError) as exc:
            raise OpeningPriceUnavailable("corrupt opening price evidence") from exc


def parse_bars(payload, *, session, instruments, observed_at, broker_symbols=None):
    """Require exact symbols, one opening minute, raw positive open and volume."""
    opened, _closed = calendar.session_window(session)
    symbols = {sid: item.symbol for sid, item in instruments.items()}
    response_symbols = symbols if broker_symbols is None else broker_symbols
    if (not instruments or any(sid != item.security_id for sid, item in instruments.items())
            or len(set(symbols.values())) != len(symbols)):
        raise OpeningPriceUnavailable("opening request instrument identities are ambiguous")
    if (set(response_symbols) != set(symbols)
            or any(not isinstance(symbol, str) or not symbol for symbol in response_symbols.values())
            or len(set(response_symbols.values())) != len(symbols)):
        raise OpeningPriceUnavailable("opening request broker symbols are ambiguous")
    if (not isinstance(payload, dict) or "next_page_token" not in payload
            or payload.get("next_page_token") is not None
            or not isinstance(payload.get("bars"), dict)
            or set(payload["bars"]) != set(response_symbols.values())):
        raise OpeningPriceUnavailable("opening bar response coverage is incomplete")
    prices = {}
    try:
        for sid, symbol in response_symbols.items():
            rows = payload["bars"][symbol]
            if not isinstance(rows, list) or len(rows) != 1:
                raise ValueError("expected exactly one opening bar")
            row = rows[0]
            timestamp = datetime.fromisoformat(row["t"])
            price, volume = Decimal(str(row["o"])), Decimal(str(row["v"]))
            if timestamp != opened or not volume.is_finite() or volume <= 0:
                raise ValueError("invalid opening bar timestamp or volume")
            prices[sid] = price
    except (TypeError, ValueError, ArithmeticError, KeyError) as exc:
        raise OpeningPriceUnavailable("opening bar evidence is invalid") from exc
    return OpeningPrices(session, opened, observed_at, prices, symbols,
                         {sid: item.broker_id for sid, item in instruments.items()})
