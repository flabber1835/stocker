"""Complete NAS ACTIONS histories, including vendor-restated older primary labels."""
from __future__ import annotations

import copy

import pytest

from sentinel.feed import symbol_identity
from test_seed_symbol_transition import OLD_LISTINGS
from test_symbol_identity_recovery import RENAMES, THROUGH


# Exact historical pairs from the operator's 2026-09-14 diagnostic. The ticker
# query returned all ten rows; the contraticker query returned only six. Names,
# null values and primary labels below are source data, not inferred aliases.
HISTORICAL_RENAMES = RENAMES + [
    {"date": day, "action": kind, "ticker": primary, "name": name,
     "value": None, "contraticker": contra, "contraname": "N/A"}
    for day, old, new, primary, name in (
        ("2019-10-29", "CHAC", "PHGE", "HLSQ", "TESSERA DEFENSE AND HOMELAND SECURITY INC"),
        ("2019-04-02", "CYCNV", "CYCN", "KRSA", "KORSANA BIOSCIENCES INC"),
        ("2019-03-15", "CHACU", "CHAC", "HLSQ", "TESSERA DEFENSE AND HOMELAND SECURITY INC"))
    for kind, contra in (("tickerchangeto", new), ("tickerchangefrom", old))]

EXPECTED_EDGES = [
    ("111101", "2019-04-02", "CYCNV", "CYCN"),
    ("111101", "2026-09-09", "CYCN", "KRSA"),
    ("113467", "2019-03-15", "CHACU", "CHAC"),
    ("113467", "2019-10-29", "CHAC", "PHGE"),
    ("113467", "2026-09-11", "PHGE", "HLSQ"),
]


@pytest.mark.parametrize("representation", ["restated", "reciprocal", "mixed", "duplicate", "intermediate"])
def test_complete_history_preserves_permanent_identity_and_effective_labels(representation):
    actions = copy.deepcopy(HISTORICAL_RENAMES)
    # Independent older reciprocal format: from primary NEW/contra OLD,
    # to primary OLD/contra NEW. Neither format needs names to infer identity.
    for i in range(0, len(actions), 2):
        if representation == "reciprocal" or (representation == "mixed" and i % 4 == 0):
            to, from_ = actions[i:i + 2]
            to["ticker"], from_["ticker"] = from_["contraticker"], to["contraticker"]
    if representation == "duplicate":
        actions += copy.deepcopy(actions)
    elif representation == "intermediate":
        for row in actions:
            if row["date"] == "2019-03-15":
                row["ticker"] = "PHGE"  # A proven later label need not be the latest.
    original = copy.deepcopy(actions)
    projection = symbol_identity.SymbolProjection(OLD_LISTINGS, reversed(actions), through=THROUGH)
    assert [(r["permaticker"], r["date"], r["old"], r["new"])
            for r in projection.evidence["renames"]] == EXPECTED_EDGES
    assert all(len(r["source_ids"]) == 2 for r in projection.evidence["renames"])
    resolver = projection.resolver()
    for sid, symbols in (("111101", ("CYCNV", "CYCN", "KRSA")),
                         ("113467", ("CHACU", "CHAC", "PHGE", "HLSQ"))):
        assert all(resolver.resolve(symbol, "2025-07-01") == sid for symbol in symbols)
    for sid, day, expected in (
        ("111101", "2019-04-01", "CYCNV"), ("111101", "2019-04-02", "CYCN"),
        ("111101", "2025-07-01", "CYCN"), ("111101", "2026-09-09", "KRSA"),
        ("113467", "2019-03-14", "CHACU"), ("113467", "2019-03-15", "CHAC"),
        ("113467", "2019-10-29", "PHGE"), ("113467", "2025-07-01", "PHGE"),
        ("113467", "2026-09-10", "PHGE"), ("113467", THROUGH, "HLSQ")):
        assert resolver.ticker_for_security(sid, day) == expected
    assert resolver.resolve("KRSA", "2019-03-15") is None  # Before the listing interval.
    assert actions == original


@pytest.mark.parametrize("fault", [
    "missing-older-to", "missing-older-from", "different-date", "extra-from", "extra-to",
    "foreign-primary", "earlier-primary", "branch", "cycle", "same-date", "conflicting-id",
])
def test_damaged_older_claims_do_not_grant_a_partial_alias(fault):
    rows = [dict(OLD_LISTINGS[0])]
    actions = [dict(r) for r in HISTORICAL_RENAMES if r["ticker"] == "KRSA"]
    if fault == "missing-older-to":
        actions.pop(2)
    elif fault == "missing-older-from":
        actions.pop(3)
    elif fault == "different-date":
        actions[2]["date"] = "2019-04-03"
    elif fault == "extra-from":
        actions.append(dict(actions[3], contraticker="OTHER"))
    elif fault == "extra-to":
        actions.append(dict(actions[2], contraticker="OTHER"))
    elif fault == "foreign-primary":
        actions[2]["ticker"] = actions[3]["ticker"] = "FOREIGN"
    elif fault == "earlier-primary":
        actions[0]["ticker"] = actions[1]["ticker"] = "CYCNV"
    elif fault == "branch":
        actions.extend([dict(actions[2], contraticker="OTHER"),
                        dict(actions[3], contraticker="CYCNV")])
    elif fault == "cycle":
        actions.extend([dict(actions[0], date="2026-09-10", contraticker="CYCNV"),
                        dict(actions[1], date="2026-09-10", contraticker="KRSA")])
    elif fault == "same-date":
        actions[0]["date"] = actions[1]["date"] = "2019-04-02"
    elif fault == "conflicting-id":
        rows.append(dict(rows[0], ticker="CYCNV", permaticker=999999))
    projection = symbol_identity.SymbolProjection(rows, actions, through=THROUGH)
    assert projection.chains == {}
    assert projection.resolver().resolve("KRSA", "2025-07-01") is None


def test_restated_primary_cannot_borrow_a_future_rename():
    projection = symbol_identity.SymbolProjection(
        OLD_LISTINGS, HISTORICAL_RENAMES, through="2025-07-01")
    assert projection.chains == {}
    assert projection.resolver().resolve("KRSA", "2025-07-01") is None
