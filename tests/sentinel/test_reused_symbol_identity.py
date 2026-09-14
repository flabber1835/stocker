"""NAS reused-ticker collision, with explicit boundaries between businesses."""
from __future__ import annotations

import copy

import pytest

from sentinel.feed import symbol_identity
from test_historical_symbol_identity import HISTORICAL_RENAMES
from test_seed_symbol_transition import OLD_LISTINGS
from test_symbol_identity_recovery import THROUGH

# Exact additional TICKERS observation supplied after the third NAS failure.
REUSED_LISTING = {
    "table": "SEP", "permaticker": 644444, "ticker": "CHACU",
    "category": "Domestic Common Stock Secondary Class", "isdelisted": "Y",
    "firstpricedate": "2025-05-19", "lastpricedate": "2026-03-26",
    "relatedtickers": "XNDU CHAC", "lastupdated": "2026-09-12",
}
REUSED_ACTIONS = [
    {"date": day, "action": kind, "ticker": "XNDU", "contraticker": contra,
     "name": "XANADU QUANTUM TECHNOLOGIES LTD", "contraname": "N/A", "value": None}
    for day, kind, contra in (
        ("2025-05-19", "tickerchangefrom", "CHACU"),
        ("2025-05-19", "tickerchangeto", "CHAC"),
        ("2026-03-27", "tickerchangefrom", "CHAC"))]
# The operator's contra filter cannot return this final self-labelled to row.
# Test both the exact partial observation above and this explicitly synthetic
# completion, rather than presenting the latter as captured vendor evidence.
COMPLETED_REUSED_ACTIONS = REUSED_ACTIONS + [dict(
    REUSED_ACTIONS[-1], action="tickerchangeto", contraticker="XNDU")]


@pytest.mark.parametrize("context", ["metadata", "partial-actions", "complete-actions"])
@pytest.mark.parametrize("representation", ["restated", "reciprocal", "mixed"])
def test_unrelated_later_reuse_cannot_poison_or_capture_phge(context, representation):
    actions = copy.deepcopy(HISTORICAL_RENAMES)
    for i in range(0, len(actions), 2):
        if representation == "reciprocal" or (representation == "mixed" and i % 4 == 0):
            to, from_ = actions[i:i + 2]
            to["ticker"], from_["ticker"] = from_["contraticker"], to["contraticker"]
    if context != "metadata":
        actions += (REUSED_ACTIONS if context == "partial-actions" else COMPLETED_REUSED_ACTIONS)
    rows = [*OLD_LISTINGS, REUSED_LISTING]
    baseline = copy.deepcopy((rows, actions))
    projection = symbol_identity.SymbolProjection(reversed(rows), reversed(actions), through=THROUGH)
    resolver = projection.resolver()
    assert resolver.resolve("HLSQ", "2025-07-01") == "113467"
    assert resolver.resolve("KRSA", "2025-07-01") == "111101"
    assert resolver.resolve("CHACU", "2025-07-01") == "644444"
    assert resolver.resolve("CHACU", "2019-03-14") == "113467"
    assert resolver.resolve("CHAC", "2019-09-01") == "113467"
    assert resolver.resolve("CHACU", THROUGH) != "113467"
    if context != "metadata":
        assert resolver.resolve("CHAC", "2025-07-01") != "113467"
    assert resolver.ticker_for_security("113467", "2025-07-01") == "PHGE"
    assert resolver.ticker_for_security("113467", THROUGH) == "HLSQ"
    assert (rows, actions) == baseline
    ordered = symbol_identity.SymbolProjection(rows, actions, through=THROUGH)
    assert projection.digest("a" * 64) == ordered.digest("a" * 64)


@pytest.mark.parametrize("fault", ["overlap", "unbounded", "same-id", "damaged-own-history"])
def test_actual_conflict_still_refuses_with_a_structured_reason(fault):
    rows = [*OLD_LISTINGS, dict(REUSED_LISTING)]
    actions = copy.deepcopy(HISTORICAL_RENAMES + COMPLETED_REUSED_ACTIONS)
    if fault == "overlap":
        rows[-1]["firstpricedate"] = "2018-12-14"
    elif fault == "unbounded":
        rows[-1]["firstpricedate"] = None
    elif fault == "same-id":
        # Both disjoint paths must be rejected if their anchor identity is one.
        rows[-1].update(permaticker=113467,
                        category=OLD_LISTINGS[1]["category"], isdelisted="N")
    else:
        actions = [r for r in actions if not (
            r["ticker"] == "HLSQ" and r["date"] == "2019-03-15"
            and r["action"] == "tickerchangeto")]
    projection = symbol_identity.SymbolProjection(rows, actions, through=THROUGH)
    assert projection.resolver().resolve("HLSQ", "2025-07-01") is None
    details = projection.explain(symbols=["HLSQ"], identities=["113467"])
    assert details["rejections"]
    assert all(r["reason_code"].startswith("RENAME_") for r in details["rejections"])


def test_two_anchored_businesses_keep_separate_histories_and_effective_labels():
    # Synthetic current metadata completes the newer business's identity too.
    current = dict(REUSED_LISTING, ticker="XNDU", isdelisted="N", lastpricedate=THROUGH)
    projection = symbol_identity.SymbolProjection(
        [*OLD_LISTINGS, REUSED_LISTING, current],
        HISTORICAL_RENAMES + COMPLETED_REUSED_ACTIONS, through=THROUGH)
    resolver = projection.resolver()
    assert resolver.resolve("HLSQ", "2025-07-01") == "113467"
    assert resolver.resolve("XNDU", "2025-07-01") == "644444"
    assert resolver.resolve("CHAC", "2019-09-01") == "113467"
    assert resolver.resolve("CHAC", "2025-07-01") == "644444"
    assert resolver.ticker_for_security("644444", "2025-07-01") == "CHAC"
    assert resolver.ticker_for_security("644444", THROUGH) == "XNDU"
    assert resolver.ticker_for_security("113467", THROUGH) == "HLSQ"
