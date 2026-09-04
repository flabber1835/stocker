#!/usr/bin/env python3
"""R1000 proxy builder with membership-authoritative historical listing semantics.

The historical IWB/R1000 snapshot itself is the experiment's listing/eligibility
authority. Current Sharadar TICKERS is used only to join the exact historical
ticker to the replay's stable security key. Current first/last pricedate bounds
must not veto contemporaneous R1000 membership.
"""
from __future__ import annotations

from backtester import build_r1000_iwb_membership as base


def map_symbol(raw_symbol: str, as_of: str, direct, compact):
    del as_of
    raw = str(raw_symbol).strip().upper()
    cleaned = raw.rstrip("*").strip()

    candidates = direct.get(cleaned, [])
    unique = {(row.ticker, row.sid) for row in candidates}
    if len(unique) == 1:
        ticker, _sid = next(iter(unique))
        return ticker, "exact" if cleaned == raw else "trailing_star"

    key = base.compact_symbol(cleaned)
    candidates = compact.get(key, [])
    unique = {(row.ticker, row.sid) for row in candidates}
    if len(unique) == 1:
        ticker, _sid = next(iter(unique))
        return ticker, "class_punctuation"
    return None, "unmapped"


base.map_symbol = map_symbol

if __name__ == "__main__":
    raise SystemExit(base.main())
