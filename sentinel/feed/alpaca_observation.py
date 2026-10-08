"""Pure, conservative projection of Alpaca pages into GO inputs."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from math import isclose, isfinite
from zoneinfo import ZoneInfo

from sentinel.feed.alpaca_transport import AlpacaTransportRefused
from sentinel.feed.rolling_contract import digest
from stock_strategy_shared.split_reconciliation import SPLIT_AGREEMENT_TOLERANCE

_NEW_YORK = ZoneInfo("America/New_York")
_SYMBOL_FIELDS = frozenset({
    "symbol", "old_symbol", "new_symbol", "source_symbol", "alternate_symbol",
    "acquiree_symbol", "acquirer_symbol", "target_symbol",
})


def action_participants(record: dict) -> frozenset[str]:
    return frozenset(str(value).strip().upper() for key, value in record.items()
                     if key in _SYMBOL_FIELDS and isinstance(value, str) and value.strip())


def structural_action_date(kind: str, record: dict) -> str | None:
    """Return a trusted economic date; unknown dates cannot clear an action."""
    field = "process_date" if kind == "name_changes" else (
        "ex_date" if record.get("ex_date") is not None else "effective_date")
    value = record.get(field)
    if not isinstance(value, str):
        return None
    try:
        parsed = date.fromisoformat(value)
        if parsed.isoformat() != value:
            return None
    except ValueError:
        return None
    return value


def cash_dividend(record: dict, *, axis: set[str], retain_historical: bool = False) -> dict | None:
    """Return one usable USD cash event; malformed selected events are refused."""
    symbol = str(record.get("symbol") or "").strip().upper()
    day = record.get("ex_date")
    if not isinstance(day, str):
        raise AlpacaTransportRefused("cash dividend lacks ex-date")
    try:
        if date.fromisoformat(day).isoformat() != day:
            raise ValueError
    except ValueError:
        raise AlpacaTransportRefused("cash dividend ex-date is invalid") from None
    if day not in axis:
        if min(axis) <= day <= max(axis):
            raise AlpacaTransportRefused("cash dividend ex-date is not an XNYS session")
        if not retain_historical or day > max(axis):
            return None
        from sentinel.feed import calendar
        if calendar.previous_sessions(day, 1) != [day]:
            raise AlpacaTransportRefused('cash dividend ex-date is not an XNYS session')
    if action_participants(record) != {symbol} or type(record.get("foreign")) is not bool:
        raise AlpacaTransportRefused("cash dividend has ambiguous participant or foreign terms")
    if record.get("currency") not in (None, "USD"):
        raise AlpacaTransportRefused("cash dividend is not denominated in USD")
    try:
        amount = Decimal(str(record.get("rate")))
    except (InvalidOperation, ValueError):
        raise AlpacaTransportRefused("cash dividend rate is invalid") from None
    if not amount.is_finite() or amount <= 0 or not isfinite(float(amount)) or float(amount) <= 0:
        raise AlpacaTransportRefused("cash dividend rate is not positive")
    dates = {}
    for field in ('process_date', 'payable_date', 'record_date'):
        value = record.get(field)
        if value is not None:
            try:
                if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
                    raise ValueError
            except ValueError:
                raise AlpacaTransportRefused('cash dividend date is invalid: ' + field) from None
        dates[field] = value
    return {"id": record["id"], "ticker": symbol, "date": day,
            "rate": format(amount.normalize(), "f"), **dates,
            'terms_sha256': digest(record)}


def stock_split(kind, record, *, axis):
    """Exact new/old share multiplier; price evidence corroborates it later."""
    if kind not in ('forward_splits', 'reverse_splits'):
        raise AlpacaTransportRefused('unsupported structural action')
    day = structural_action_date(kind, record)
    symbol = record.get('symbol')
    if day not in axis or action_participants(record) != {symbol}:
        raise AlpacaTransportRefused('split has invalid session or participants')
    try:
        old, new = Decimal(str(record['old_rate'])), Decimal(str(record['new_rate']))
        if not old.is_finite() or not new.is_finite() or min(old, new) <= 0:
            raise ValueError
        ratio = new / old
        if ratio == 1 or (kind == 'forward_splits') != (ratio > 1):
            raise ValueError
        if not isfinite(float(ratio)) or float(ratio) <= 0:
            raise ValueError
    except (KeyError, InvalidOperation, ValueError, OverflowError):
        raise AlpacaTransportRefused('split terms are missing or inconsistent') from None
    return {'id': record['id'], 'ticker':symbol, 'date':day,
            'ratio':format(ratio.normalize(), 'f')}


def action_symbols(pages, *, start: str, end: str) -> tuple[frozenset[str], dict]:
    """Quarantine every named participant in any observed action.

    ``start``/``end`` bound process_date, the Alpaca API's query dimension.
    This is deliberately wider than the formation ex-date interval.
    """
    by_id = {}
    counts = defaultdict(int)
    for page in pages:
        if not isinstance(page, dict):
            raise AlpacaTransportRefused("corporate-action page is not an object")
        for kind, records in page.items():
            if not isinstance(kind, str) or not isinstance(records, list):
                raise AlpacaTransportRefused("corporate-action type is malformed")
            for record in records:
                if not isinstance(record, dict) or not isinstance(record.get("id"), str):
                    raise AlpacaTransportRefused("corporate action lacks an identity")
                date = record.get("process_date")
                if not isinstance(date, str) or not start <= date <= end:
                    raise AlpacaTransportRefused("corporate action escaped its process-date query")
                symbols = action_participants(record)
                if not symbols:
                    raise AlpacaTransportRefused("corporate action lacks symbol participants")
                prior = by_id.get(record["id"])
                observation = (kind, record)
                if prior is not None and prior != observation:
                    raise AlpacaTransportRefused("corporate action identity changed across pages")
                if prior is None:
                    by_id[record["id"]] = observation
                    counts[kind] += 1
    symbols = frozenset(symbol for _kind, record in by_id.values()
                        for symbol in action_participants(record))
    return symbols, {"actions": len(by_id), "by_type": dict(sorted(counts.items())),
                     "affected_symbols": len(symbols)}


def _day(stamp: str) -> str:
    if not isinstance(stamp, str):
        raise AlpacaTransportRefused("bar timestamp is absent")
    try:
        parsed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError
        return parsed.astimezone(_NEW_YORK).date().isoformat()
    except ValueError:
        raise AlpacaTransportRefused("bar timestamp is not an aware ISO time") from None


def bar_page_rows(page, *, symbols: set[str], sessions: set[str]):
    """Validate one complete price page without assuming symbol order."""
    if not isinstance(page, dict):
        raise AlpacaTransportRefused("bar page is not an object")
    rows = {}
    for symbol, records in page.items():
        if symbol not in symbols or not isinstance(records, list):
            raise AlpacaTransportRefused("bar page contains unexpected security")
        for record in records:
            if not isinstance(record, dict):
                raise AlpacaTransportRefused("bar record is not an object")
            day = _day(record.get("t"))
            if day not in sessions or (symbol, day) in rows:
                raise AlpacaTransportRefused("bar is outside axis or duplicated")
            for field in ("o", "c", "v"):
                value = record.get(field)
                if (not isinstance(value, (int, float)) or isinstance(value, bool)
                        or not isfinite(value) or (value <= 0 if field != "v" else value < 0)):
                    raise AlpacaTransportRefused("bar has invalid economic domains")
            rows[(symbol, day)] = {"open": record["o"], "close": record["c"],
                                   "volume": record["v"]}
    return rows


def paired_month(raw, adjusted, *, symbols: set[str], sessions: set[str]):
    """Preserve raw prices plus independent adjustment evidence per key."""
    left = bar_page_rows(raw, symbols=symbols, sessions=sessions)
    right = bar_page_rows(adjusted, symbols=symbols, sessions=sessions)
    absent = set(left) ^ set(right)
    rows = []
    for symbol, day in sorted(set(left) & set(right), key=lambda key: (key[1], key[0])):
        bar = left[(symbol, day)]
        rows.append({"ticker": symbol, "date": day, "open": bar["open"],
                     "close": bar["close"], "closeunadj": bar["close"],
                     "volume": bar["volume"], "adjusted_close": right[(symbol, day)]["close"]})
    return rows, absent


def _adjustment_interval(row: dict, factor: Decimal) -> tuple[float, float]:
    """Corroborate explicit terms within the observed adjusted-price precision."""
    adjusted, raw = row['adjusted_close'], row['closeunadj']
    radius = adjusted * .00025
    if isclose(adjusted, round(adjusted, 2), rel_tol=0, abs_tol=1e-12):
        radius = min(.005, adjusted * SPLIT_AGREEMENT_TOLERANCE)
    scale = raw * float(factor)
    if not isfinite(scale) or scale <= 0:
        raise AlpacaTransportRefused("retained split adjustment scale is invalid")
    lo, hi = (adjusted - radius) / scale, (adjusted + radius) / scale
    if not isfinite(lo) or not isfinite(hi) or lo <= 0:
        raise AlpacaTransportRefused("retained split adjustment interval is invalid")
    return lo, hi


def admissible_history(rows, *, axis: list[str], symbols: set[str],
                       action_affected: frozenset[str], pair_absent: set[tuple[str, str]],
                       dividend_dates: dict[str, set[str]] | None = None,
                       reset_after: dict[str, str] | None = None,
                       split_terms: dict[tuple[str, str], str] | None = None):
    """Return usable contiguous tails, never inventing a missing observation.

    The published candidate history starts after its last gap. Protected book
    anchors and already-applied economics are checked separately by continuity.
    """
    index = {day: position for position, day in enumerate(axis)}
    by_symbol = {}
    split_symbols = {symbol for symbol, _day in (split_terms or {})}
    previous = None
    for row in rows:
        symbol, day = row["ticker"], row["date"]
        key = (day, symbol)
        if (symbol not in symbols or day not in index
                or (previous is not None and key <= previous)):
            raise AlpacaTransportRefused("retained bar identities are duplicate, unordered or foreign")
        previous = key
        if day <= (reset_after or {}).get(symbol, ""):
            continue
        position = index[day]
        ratio = row["adjusted_close"] / row["closeunadj"]
        if not isfinite(ratio) or ratio <= 0:
            raise AlpacaTransportRefused("retained bar adjustment is invalid")
        current = by_symbol.get(symbol)
        if current is None or position != current[1] + 1:
            lo, hi = _adjustment_interval(row, Decimal(1))
            by_symbol[symbol] = [position, position, 1, ratio, ratio, Decimal(1), lo, hi]
        else:
            current[5] *= Decimal((split_terms or {}).get((symbol, day), '1'))
            normalized = ratio / float(current[5])
            current[1] = position
            current[2] += 1
            current[3] = min(current[3], normalized)
            current[4] = max(current[4], normalized)
            lo, hi = _adjustment_interval(row, current[5])
            current[6], current[7] = max(current[6], lo), min(current[7], hi)
    admitted, reasons = {}, defaultdict(int)
    for symbol in sorted(symbols):
        observed = by_symbol.get(symbol)
        if symbol in action_affected:
            reasons["reported_corporate_action"] += 1
        elif any(pair_symbol == symbol and pair_day >= (
                    axis[observed[0]] if observed else axis[0])
                 and pair_day > (reset_after or {}).get(symbol, "")
                 for pair_symbol, pair_day in pair_absent):
            reasons["raw_adjusted_key_mismatch"] += 1
        elif observed is None:
            reasons["no_prices"] += 1
        else:
            first, last, count, lo, hi, _factor, rounded_lo, rounded_hi = observed
            if last != len(axis) - 1 or count != len(axis) - first:
                reasons["noncontiguous_or_stale_prices"] += 1
                continue
            if hi / lo - 1 > 0.0005 and (symbol not in split_symbols
                    or rounded_lo > rounded_hi * (1 + 1e-12)):
                reasons["adjustment_discontinuity"] += 1
                continue
            if (symbol, axis[first]) in (split_terms or {}):
                reasons['split_predecessor_missing'] += 1
                continue
            if any(day > axis[last]
                   for day in (dividend_dates or {}).get(symbol, ())):
                reasons["cash_dividend_outside_price_history"] += 1
                continue
            admitted[symbol] = axis[first]
    return admitted, dict(sorted(reasons.items()))
