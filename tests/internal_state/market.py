"""Fictional economic facts encoded for the existing Sharadar HTTP provider."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from fractions import Fraction
import math

from research.sharadar_replay.model import Corpus, Fault, Step
from research.sharadar_replay.oracle import compare
from sentinel.feed import calendar

SYMBOLS = tuple(f"S{i:03d}" for i in range(30))
AUTHORITY_TICKER = "TRI"
AUTHORITY_SECURITY = "STATE-TRI-AUTHORITY"
AUTHORITY_SESSION = "2026-05-04"
AUTHORITY_PREVIOUS_SESSION = "2026-05-01"
AUTHORITY_STALE_CASH = 1.36
AUTHORITY_FINAL_CASH = 1.435518
SECURITIES = ({symbol: f"STATE-{symbol}" for symbol in SYMBOLS}
              | {"BIL": "SENTINEL:BIL", AUTHORITY_TICKER: AUTHORITY_SECURITY})
SEED = "2026-08-17"
FIRST = "2026-08-18"
START = "2025-08-01"


def sessions(through):
    return calendar.sessions_in_range(START, through)


def compare_corpus(expected: Corpus, actual: Corpus):
    """Reuse the exact provider oracle at the declared float-storage precision."""
    def numeric_columns(corpus):
        fields = {}
        for name, columns in (("bars", range(3, 9)), ("spy", (1,)),
                              ("defensive", range(3, 7))):
            fields[name] = tuple(tuple(
                Decimal(str(value)).quantize(Decimal("0.00000001"))
                if index in columns else value
                for index, value in enumerate(row)) for row in getattr(corpus, name))
        return corpus.model_copy(update=fields)
    compare(numeric_columns(expected), numeric_columns(actual))


def raw_price(symbol, index, seed):
    number = SYMBOLS.index(symbol)
    # Positive formation returns, distinct opens, finite nonzero variance.
    return round(50 + number * 2 + index * (0.2 + number * 0.002)
                 + math.sin(index * (0.17 + number * 0.002) + seed) * 0.2, 6)


def step(day: str, seed=0, *, faulty=False, shocks=(), observed_after=None):
    axis = sessions(day)
    tables = {name: [] for name in ("SEP", "SFP", "TICKERS", "ACTIONS")}
    bars, actions, identities, spy, defensive = [], [], [], [], []
    for symbol in SYMBOLS:
        sid = SECURITIES[symbol]
        tables["TICKERS"].append(dict(table="SEP", ticker=symbol, permaticker=sid,
            category="Domestic Common Stock", sector="Industrials", exchange="NYSE",
            relatedtickers="", firstpricedate=START, lastpricedate=day, isdelisted="N"))
        identities.append((sid, symbol, "Domestic Common Stock", "Industrials", "", START, day, False))
        tables["ACTIONS"].append(dict(ticker=symbol, date=START, action="listed",
                                      name=symbol, value=None, contraticker=None, contraname=None))
        actions.append((symbol, START, "listed", symbol, None, None, None))
        for index, session in enumerate(axis):
            factor = math.prod(1 + basis_points / 10000 for start, basis_points in shocks if session >= start)
            close = round(raw_price(symbol, index, seed) * factor, 6)
            opened = round(close * (1 + (SYMBOLS.index(symbol) % 5 - 2) * 0.0002), 6)
            volume = 2_000_000 + index * 100 + SYMBOLS.index(symbol)
            tables["SEP"].append(dict(ticker=symbol, date=session, open=opened,
                close=close, closeunadj=close, volume=volume, lastupdated=session))
            bars.append((sid, session, symbol, close, close, opened, volume, 1,
                         0.5 if symbol == SYMBOLS[0] and session == "2026-07-01" else 0))
    tables["ACTIONS"].append(dict(ticker=SYMBOLS[0], date="2026-07-01", action="dividend",
        name=SYMBOLS[0], value=0.5, contraticker=None, contraname=None))
    actions.append((SYMBOLS[0], "2026-07-01", "dividend", SYMBOLS[0], 0.5, None, None))

    # The production corporate-action authority contains one reviewed historical
    # dispute. The synthetic lab must carry that exact stale Sharadar source fact
    # once the event is in its observed history; otherwise the production code is
    # expected to fail closed before lifecycle testing can begin. Include the
    # predecessor and consolidation so the fixture proves the issuer's old-share
    # cash basis. Two observations keep it outside the formation universe.
    if AUTHORITY_SESSION in axis:
        tables["TICKERS"].append(dict(
            table="SEP", ticker=AUTHORITY_TICKER, permaticker=AUTHORITY_SECURITY,
            category="Domestic Common Stock", sector="Industrials", exchange="NYSE",
            relatedtickers="", firstpricedate=AUTHORITY_PREVIOUS_SESSION,
            lastpricedate=AUTHORITY_SESSION, isdelisted="Y"))
        identities.append((
            AUTHORITY_SECURITY, AUTHORITY_TICKER, "Domestic Common Stock",
            "Industrials", "", AUTHORITY_PREVIOUS_SESSION, AUTHORITY_SESSION, True))
        for action, value in (("dividend", AUTHORITY_STALE_CASH), ("split", 0.984560)):
            tables["ACTIONS"].append(dict(
                ticker=AUTHORITY_TICKER, date=AUTHORITY_SESSION, action=action,
                name=AUTHORITY_TICKER, value=value, contraticker=None, contraname=None))
            actions.append((AUTHORITY_TICKER, AUTHORITY_SESSION, action,
                            AUTHORITY_TICKER, value, None, None))
        for session, raw, raw_open, vendor_volume, ratio, cash in (
                (AUTHORITY_PREVIOUS_SESSION, 98.456, 97.96372, 984_560, 1, 0),
                (AUTHORITY_SESSION, 100.0, 99.5, 1_000_000, 0.984560,
                 float(Fraction(str(AUTHORITY_FINAL_CASH)) / Fraction("0.984560")))):
            tables["SEP"].append(dict(
                ticker=AUTHORITY_TICKER, date=session, open=99.5,
                close=100.0, closeunadj=raw, volume=vendor_volume, lastupdated=session))
            bars.append((AUTHORITY_SECURITY, session, AUTHORITY_TICKER,
                         100.0, raw, raw_open, 1_000_000, ratio, cash))

    for index, session in enumerate(axis):
        for ticker, base in (("SPY", 400), ("BIL", 100)):
            factor = math.prod(1 + basis_points / 10000 for start, basis_points in shocks if session >= start)
            close = (base + index / 100) * (factor if ticker == "SPY" else 1)
            tables["SFP"].append(dict(ticker=ticker, date=session, open=close - 0.1,
                close=close, closeadj=close, closeunadj=close))
        spy.append((session, (400 + index / 100) * factor))
        defensive.append((session, "SENTINEL:BIL", "BIL", 99.9 + index / 100,
                          100 + index / 100, 100 + index / 100, 100 + index / 100))
    expected = Corpus(bars=tuple(bars), actions=tuple(actions), identities=tuple(identities),
                      spy=tuple(spy), defensive=tuple(defensive))
    observed_at = datetime.fromisoformat(day + "T22:00:00+00:00")
    if observed_after is not None:
        observed_at = max(observed_at, observed_after + timedelta(seconds=1))
    return Step(name="session_" + day.replace("-", ""),
        at=observed_at, through=date.fromisoformat(day),
        tables={k: tuple(v) for k, v in tables.items()}, expected=expected,
        faults=(Fault(table="ACTIONS", kind="http_400"),) if faulty else ())
