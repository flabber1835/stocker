"""Typed execution-only evidence for the first regular-session raw open."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from types import MappingProxyType
from typing import Mapping

from sentinel.feed import calendar

SOURCE = "ALPACA_IEX_RAW_OPENING_MINUTE_V1"
QUOTE_SOURCE = "ALPACA_IEX_RAW_REGULAR_QUOTES_V2"
QUOTE_ENDPOINT = "https://data.alpaca.markets/v2/stocks/quotes/latest"
FEED = "iex"
UNAVAILABLE_SOURCE = "ALPACA_OPENING_EVIDENCE_UNAVAILABLE_V1"
ENDPOINT = "https://data.alpaca.markets/v2/stocks/bars"


class OpeningPriceUnavailable(RuntimeError):
    """The opening evidence is incomplete or unavailable for this attempt."""


class OpeningPriceNotReady(OpeningPriceUnavailable):
    """The named opening minute is still forming and sizing may retry."""


@dataclass(frozen=True)
class OpeningPriceUnavailability:
    """Durable proof that no opening BUY may be sized from this attempt.

    Reductions do not depend on an entry opening price.  Preserving this typed
    result lets the executor continue risk-reducing work while making the
    unavailable BUY explicit and permanently zero for this immutable plan.
    """
    session: date
    reason: str
    symbols: Mapping[str, str]
    broker_ids: Mapping[str, str]
    source: str = UNAVAILABLE_SOURCE

    def __post_init__(self):
        if self.source != UNAVAILABLE_SOURCE or not isinstance(self.reason, str) or not self.reason.strip():
            raise OpeningPriceUnavailable("opening unavailability evidence is invalid")
        if (any(not isinstance(sid, str) or not sid for sid in self.symbols)
                or any(not isinstance(symbol, str) or not symbol for symbol in self.symbols.values())
                or len(set(self.symbols.values())) != len(self.symbols)):
            raise OpeningPriceUnavailable("opening unavailability symbols are ambiguous")
        if (set(self.broker_ids) != set(self.symbols)
                or any(not isinstance(asset, str) or not asset.strip()
                       for asset in self.broker_ids.values())
                or len(set(self.broker_ids.values())) != len(self.broker_ids)):
            raise OpeningPriceUnavailable("opening unavailability broker identities are ambiguous")
        object.__setattr__(self, "symbols", MappingProxyType(dict(self.symbols)))
        object.__setattr__(self, "broker_ids", MappingProxyType(dict(self.broker_ids)))

    @property
    def prices(self):
        return MappingProxyType({})

    def to_dict(self):
        return {"source": self.source, "session": self.session.isoformat(),
                "reason": self.reason,
                "symbols": dict(sorted(self.symbols.items())),
                "broker_ids": dict(sorted(self.broker_ids.items()))}

    @classmethod
    def from_dict(cls, raw):
        if not isinstance(raw, dict) or set(raw) != {
                "source", "session", "reason", "symbols", "broker_ids"}:
            raise OpeningPriceUnavailable("invalid opening unavailability evidence shape")
        try:
            return cls(date.fromisoformat(raw["session"]), raw["reason"],
                       raw["symbols"], raw["broker_ids"], raw["source"])
        except (TypeError, ValueError, AttributeError) as exc:
            raise OpeningPriceUnavailable("corrupt opening unavailability evidence") from exc


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
        if self.source == QUOTE_SOURCE and not isinstance(self, RegularQuotes):
            raise OpeningPriceUnavailable('regular quotes require authenticated sides and timestamps')
        if (self.source not in {SOURCE, QUOTE_SOURCE} or self.opening_at != opened
                or self.observed_at.tzinfo is None
                or not opened + (timedelta(minutes=1) if self.source == SOURCE else timedelta(0)) <= self.observed_at < closed):
            raise OpeningPriceUnavailable("opening prices have invalid source or session timestamps")
        coverage_valid = (set(self.prices) == set(self.symbols) if self.source == SOURCE
                          else set(self.prices) <= set(self.symbols))
        if (not self.prices or not coverage_valid
                or any(not isinstance(sid, str) or not sid for sid in self.prices)
                or len(set(self.symbols.values())) != len(self.symbols)
                or any(not isinstance(symbol, str) or not symbol for symbol in self.symbols.values())):
            raise OpeningPriceUnavailable("opening prices have incomplete or ambiguous identities")
        if (set(self.broker_ids) != set(self.symbols)
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
        if isinstance(raw, dict) and raw.get('source') == QUOTE_SOURCE:
            return RegularQuotes.from_dict(raw)
        if isinstance(raw, dict) and raw.get("source") == UNAVAILABLE_SOURCE:
            return OpeningPriceUnavailability.from_dict(raw)
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


@dataclass(frozen=True)
class RegularQuotes(OpeningPrices):
    """Raw asks fund entries; raw bids conservatively value pending sales."""
    bids: Mapping[str, Decimal] = None
    quoted_at: Mapping[str, datetime] = None
    source: str = QUOTE_SOURCE

    def __post_init__(self):
        super().__post_init__()
        if (self.source != QUOTE_SOURCE or self.bids is None or self.quoted_at is None
                or set(self.bids) != set(self.prices) or set(self.quoted_at) != set(self.prices)):
            raise OpeningPriceUnavailable('regular quote evidence has incomplete sides or timestamps')
        for sid, ask in self.prices.items():
            bid, stamp = self.bids[sid], self.quoted_at[sid]
            if (not isinstance(bid, Decimal) or not bid.is_finite() or not 0 < bid <= ask
                    or not isinstance(stamp, datetime) or stamp.utcoffset() is None
                    or not self.opening_at <= stamp <= self.observed_at
                    or self.observed_at - stamp > timedelta(seconds=60)):
                raise OpeningPriceUnavailable('regular quote is invalid, crossed, stale or outside session')
        object.__setattr__(self, 'bids', MappingProxyType(dict(self.bids)))
        object.__setattr__(self, 'quoted_at', MappingProxyType(dict(self.quoted_at)))

    def to_dict(self):
        return {**super().to_dict(), 'bids':{sid:str(p) for sid,p in sorted(self.bids.items())},
                'quoted_at':{sid:t.isoformat() for sid,t in sorted(self.quoted_at.items())}}

    @classmethod
    def from_dict(cls, raw):
        if not isinstance(raw, dict) or set(raw) != {
                'source','session','opening_at','observed_at','prices','symbols','broker_ids','bids','quoted_at'}:
            raise OpeningPriceUnavailable('invalid regular quote evidence shape')
        try:
            return cls(session=date.fromisoformat(raw['session']),
                opening_at=datetime.fromisoformat(raw['opening_at']), observed_at=datetime.fromisoformat(raw['observed_at']),
                prices={sid:Decimal(p) for sid,p in raw['prices'].items()}, symbols=raw['symbols'],
                broker_ids=raw['broker_ids'], source=raw['source'],
                bids={sid:Decimal(p) for sid,p in raw['bids'].items()},
                quoted_at={sid:datetime.fromisoformat(t) for sid,t in raw['quoted_at'].items()})
        except (TypeError, ValueError, ArithmeticError, AttributeError) as exc:
            raise OpeningPriceUnavailable('corrupt regular quote evidence') from exc


def parse_quotes(payload, *, session, instruments, observed_at, broker_symbols):
    opened, _ = calendar.session_window(session)
    symbols = {sid:item.symbol for sid,item in instruments.items()}
    if (not instruments or any(sid != item.security_id for sid,item in instruments.items())
            or set(broker_symbols) != set(symbols) or len(set(broker_symbols.values())) != len(symbols)
            or not isinstance(payload, dict) or not isinstance(payload.get('quotes'), dict)
            or not set(payload['quotes']) <= set(broker_symbols.values())):
        raise OpeningPriceUnavailable('regular quote response identities are invalid')
    asks, bids, stamps = {}, {}, {}
    for sid, symbol in broker_symbols.items():
        row = payload['quotes'].get(symbol)
        if row is None:
            continue
        try:
            if not isinstance(row, dict):
                raise ValueError
            ask, bid = Decimal(str(row['ap'])), Decimal(str(row['bp']))
            stamp = datetime.fromisoformat(row['t'].replace('Z','+00:00'))
            ask_size, bid_size = Decimal(str(row['as'])), Decimal(str(row['bs']))
            if (not all(p.is_finite() and p > 0 for p in (ask,bid,ask_size,bid_size))
                    or bid > ask or stamp.utcoffset() is None or not opened <= stamp <= observed_at
                    or observed_at - stamp > timedelta(seconds=60)):
                continue  # Security-specific unavailable observation; never invent a price.
        except (KeyError, TypeError, ValueError, ArithmeticError, AttributeError):
            continue
        asks[sid], bids[sid], stamps[sid] = ask, bid, stamp
    if not asks:
        raise OpeningPriceNotReady('no fresh regular-session IEX quotes; retry within execution window')
    return RegularQuotes(session=session, opening_at=opened, observed_at=observed_at,
        prices=asks, symbols=symbols, broker_ids={sid:item.broker_id for sid,item in instruments.items()},
        bids=bids, quoted_at=stamps)


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
