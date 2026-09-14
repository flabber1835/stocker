"""NAS source mismatch: restated SEP symbols precede their TICKERS identities."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys

import pytest

from sentinel.feed import coherence, seed_capture, sharadar, source_authority

ROOT = Path(os.environ.get("SENTINEL_REPO_ROOT") or Path(__file__).resolve().parents[2])
sys.path.insert(0, str(ROOT / "scripts"))
import sentinel_go_24x7_entry as go_entry


DAY = "2026-09-08"
# Observed NAS rows, 2026-09-14T00:46:47Z. Sector is a synthetic metadata input
# because the bounded operator probe does not request it.
OLD_LISTINGS = (
    {"table": "SEP", "permaticker": 111101, "ticker": "CYCN",
     "category": "Domestic Common Stock", "relatedtickers": "CYCNV",
     "firstpricedate": "2019-03-18", "lastpricedate": "2026-09-08",
     "lastupdated": "2026-09-12", "isdelisted": "N", "sector": "Healthcare"},
    {"table": "SEP", "permaticker": 113467, "ticker": "PHGE",
     "category": "Domestic Common Stock Primary Class",
     "relatedtickers": "CHACU CHAC.U CHAC PHGE.U",
     "firstpricedate": "2018-12-14", "lastpricedate": "2026-09-11",
     "lastupdated": "2026-09-12", "isdelisted": "N", "sector": "Healthcare"},
)
RESTATED_BARS = (
    {"ticker": "KRSA", "date": DAY, "open": 26.04, "close": 23.94,
     "closeunadj": 3.42, "volume": 8900.0, "lastupdated": "2026-09-13"},
    {"ticker": "HLSQ", "date": DAY, "open": 1.5, "close": 1.55,
     "closeunadj": 0.155, "volume": 64400.0, "lastupdated": "2026-09-13"},
)


@pytest.mark.parametrize("metadata,missing_bar,missing,unresolved", [
    ("stale", False, ["CYCN", "PHGE"], ["HLSQ", "KRSA"]),
    ("one-updated", False, ["PHGE"], ["HLSQ"]),
    ("consistent", False, [], []),
    ("consistent", True, ["KRSA"], []),
])
def test_real_seed_capture_refuses_mismatch_and_accepts_consistent_reference(
        metadata, missing_bar, missing, unresolved):
    # Meet production population floors; no coverage thresholds are mocked.
    listings = [dict(OLD_LISTINGS[0], ticker="T%s" % i, permaticker=str(i),
                     firstpricedate=DAY, lastpricedate=DAY) for i in range(5604)]
    bars = [dict(RESTATED_BARS[0], ticker=row["ticker"]) for row in listings]
    for index, old in enumerate(OLD_LISTINGS):
        updated = metadata == "consistent" or (metadata == "one-updated" and index == 0)
        listings.append(dict(old, ticker=RESTATED_BARS[index]["ticker"],
                             lastpricedate="2026-09-11") if updated else dict(old))
    bars.extend(dict(row) for row in RESTATED_BARS
                if not (missing_bar and row["ticker"] == "KRSA"))
    calls = []

    def fetch(table, params=None):
        calls.append(table)
        rows = {sharadar.TICKERS: listings, sharadar.SEP: bars,
                sharadar.ACTIONS: [], sharadar.SFP: [
                    {"ticker": "SPY", "date": DAY, "closeadj": 600.0}]}[table]
        return [dict(row) for row in rows]

    guarded = source_authority.StableSharadarFetch(fetch, seed_mode=True)
    params = sharadar.date_params(DAY, DAY)
    with seed_capture.CapturedRows() as captured:
        captured.capture(guarded, sharadar.TICKERS)
        captured.capture(guarded, sharadar.ACTIONS, params)
        captured.capture(guarded, sharadar.SFP, params)
        if missing:
            with pytest.raises(coherence.SeedHistoryIncomplete) as caught:
                captured.capture(guarded, sharadar.SEP, params)
            payload = json.loads(str(caught.value).split(": ", 1)[1])
            assert payload["session"] == DAY
            assert payload["expected_eligible"] == 5606
            assert payload["received_eligible"] == 5606 - len(missing)
            assert [row["ticker"] for row in payload["missing_eligible"]] == missing
            assert payload["unresolved_source_tickers"] == unresolved
            assert guarded.seed_coverage_evidence is None
            assert all(key[0] != sharadar.SEP for key in captured.files)
            namespace = {}
            exec(go_entry._PREPARATION_CODE.split("\ndef emit_failure", 1)[0], namespace)
            detail = namespace["failure_detail"](caught.value)["detail"]
            for symbol in missing + unresolved:
                assert symbol in detail
        else:
            captured.capture(guarded, sharadar.SEP, params)
            replay = list(captured(sharadar.SEP, params))
            assert replay == bars  # Preserve source prices, units and symbols.
            assert guarded.seed_coverage_evidence["received_eligible_total"] == 5606
            assert guarded.seed_coverage_evidence["missing_eligible_total"] == 0
            for old, bar in zip(OLD_LISTINGS, RESTATED_BARS):
                assert guarded._seed_resolver.resolve(bar["ticker"], DAY) == str(old["permaticker"])
        spools = list(captured.files.values())
    assert all(spool.closed for spool in spools)
    assert calls.count(sharadar.SEP) == 2
    assert calls.count(sharadar.TICKERS) == 2
    assert calls.count(sharadar.ACTIONS) == 2
    assert calls.count(sharadar.SFP) == 2


def test_unresolved_symbol_diagnostic_is_bounded_and_order_independent():
    def refusal(symbols):
        projection = source_authority.SeedListingProjection(
            OLD_LISTINGS, source_digest="a" * 64)
        coverage = source_authority.SeedCoverageAccumulator(
            projection, lambda ticker, session: None)
        try:
            for symbol in symbols:
                coverage.add(dict(RESTATED_BARS[0], ticker=symbol))
            with pytest.raises(source_authority.SourceAuthorityRefused) as caught:
                coverage.require_complete(date_from=DAY, date_to=DAY)
            return str(caught.value)
        finally:
            coverage.close()

    symbols = ["UNKNOWN%02d" % i for i in range(25)]
    forward = refusal(symbols)
    assert refusal(reversed(symbols)) == forward
    assert json.loads(forward.split(": ", 1)[1])["unresolved_source_tickers"] == symbols[:16]


def test_diagnostic_does_not_make_unclassified_rows_eligible_or_a_new_refusal():
    projection = source_authority.SeedListingProjection(OLD_LISTINGS, source_digest="a" * 64)
    identities = {row["ticker"]: str(row["permaticker"]) for row in OLD_LISTINGS}
    coverage = source_authority.SeedCoverageAccumulator(
        projection, lambda ticker, session: identities.get(ticker))
    try:
        for symbol in [*identities, "UNCLASSIFIED"]:
            coverage.add(dict(RESTATED_BARS[0], ticker=symbol))
        result = coverage.require_complete(date_from=DAY, date_to=DAY)
        assert result["expected_eligible_total"] == result["received_eligible_total"] == 2
    finally:
        coverage.close()
