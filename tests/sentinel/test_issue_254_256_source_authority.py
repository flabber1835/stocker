"""Falsifiers for issues #254, #255, and #256."""
from __future__ import annotations

import datetime as dt
import json

import pytest

from sentinel.feed import maintenance, sharadar, source_authority, staging


def _sep(ticker="AAA", date="2026-08-21", *,
         lastupdated="2026-08-21", **changes):
    row = {"ticker": ticker, "date": date, "open": 10.0, "close": 10.0,
           "closeunadj": 10.0, "volume": 1000.0,
           "lastupdated": lastupdated}
    row.update(changes)
    return row


def _fetch(rows):
    return lambda table, params=None, **kwargs: iter(
        [dict(row) for row in rows])


def test_seed_watermark_refuses_future_without_partial_maximum():
    tracker = maintenance.LastUpdatedTrackingFetch(
        _fetch([_sep("A", lastupdated="2026-08-20"),
                _sep("B", lastupdated="2099-01-01")]),
        update_ceiling="2026-08-24")
    with pytest.raises(source_authority.SepUpdateEnvelopeViolation,
                       match="causal ceiling"):
        list(tracker(sharadar.SEP))
    assert tracker.max_sep_lastupdated is None


def test_seed_watermark_malformed_refuses_and_exact_ceiling_passes():
    bad = maintenance.LastUpdatedTrackingFetch(
        _fetch([_sep(lastupdated="bad")]), update_ceiling="2026-08-24")
    with pytest.raises(source_authority.SepUpdateEnvelopeViolation,
                       match="strict ISO date"):
        list(bad(sharadar.SEP))
    assert bad.max_sep_lastupdated is None

    exact = maintenance.LastUpdatedTrackingFetch(
        _fetch([_sep(lastupdated="2026-08-24")]),
        update_ceiling="2026-08-24")
    assert list(exact(sharadar.SEP))
    assert exact.max_sep_lastupdated == dt.date(2026, 8, 24)


def test_production_complete_seed_separates_vendor_clock_from_market_frontier():
    class ProductionSeedSource:
        _seed_mode = True

        def __call__(self, table, params=None, **kwargs):
            assert table == sharadar.SEP
            return iter([_sep(
                "ZTEKF", date="2025-12-31", lastupdated="2026-09-03")])

    # This reproduces the NAS 24x7 recovery failure: the retained market seed is
    # intentionally bounded through 2026-09-02 while the current complete vendor
    # snapshot contains an old row revised on 2026-09-03. Production seed
    # authority follows the vendor-observation clock; deterministic injected
    # sources below retain the explicit historical ceiling.
    tracker = maintenance.LastUpdatedTrackingFetch(
        ProductionSeedSource(), update_ceiling="2026-09-02")
    rows = list(tracker(sharadar.SEP))
    assert rows[0]["ticker"] == "ZTEKF"
    assert tracker.max_sep_lastupdated == dt.date(2026, 9, 3)


def test_abandoned_seed_traversal_cannot_commit_watermark():
    tracker = maintenance.LastUpdatedTrackingFetch(
        _fetch([_sep("A"), _sep("B")]), update_ceiling="2026-08-24")
    rows = tracker(sharadar.SEP)
    next(rows)
    rows.close()
    assert tracker.max_sep_lastupdated is None


@pytest.mark.parametrize("value", ["2026-07-31", "2026-08-06", "bad", None])
def test_cdc_exact_update_interval_refuses_outside_or_missing(value):
    envelope = source_authority.SepUpdateEnvelope.interval(
        "2026-08-01", "2026-08-05")
    guarded = source_authority.CanonicalSourceFetch(
        _fetch([_sep(lastupdated=value)]), sep_update_envelope=envelope)
    with pytest.raises(source_authority.SepUpdateEnvelopeViolation):
        list(guarded(sharadar.SEP, {
            "lastupdated.gte": "2026-08-01",
            "lastupdated.lte": "2026-08-05"}))


@pytest.mark.parametrize("value", ["2026-08-01", "2026-08-05"])
def test_cdc_exact_update_interval_edges_pass(value):
    envelope = source_authority.SepUpdateEnvelope.interval(
        "2026-08-01", "2026-08-05")
    guarded = source_authority.CanonicalSourceFetch(
        _fetch([_sep(lastupdated=value)]), sep_update_envelope=envelope)
    assert list(guarded(sharadar.SEP, {
        "lastupdated.gte": "2026-08-01",
        "lastupdated.lte": "2026-08-05"}))


def _duplicate_message(rows, table=sharadar.SEP):
    with pytest.raises(source_authority.CanonicalSourceDuplicate) as caught:
        list(source_authority.validated_source_rows(table, rows))
    return str(caught.value)


def test_conflicting_duplicate_evidence_is_order_independent():
    one = _sep(close=10.0, volume=1000)
    two = _sep(close=11.0, volume=2000)
    forward = _duplicate_message([one, two])
    reverse = _duplicate_message([two, one])
    assert forward == reverse
    evidence = json.loads(forward.split(": ", 1)[1])
    assert evidence["key"] == {"ticker": "AAA", "date": "2026-08-21"}
    assert evidence["multiplicity"] == 2
    assert evidence["conflicting_fields"] == ["close", "volume"]


def test_identical_duplicate_and_sfp_duplicate_refuse_actions_unchanged():
    row = _sep()
    evidence = json.loads(
        _duplicate_message([row, dict(row)]).split(": ", 1)[1])
    assert evidence["identical_duplicate_policy"] == "reject"
    assert evidence["row_fingerprints"][0]["count"] == 2

    sfp = {"ticker": "SPY", "date": "2026-08-21", "closeadj": 600.0}
    assert '\"table\":\"SFP\"' in _duplicate_message(
        [sfp, dict(sfp, closeadj=601.0)], sharadar.SFP)

    actions = [{"ticker": "AAA", "date": "2026-08-21", "action": "split"},
               {"ticker": "AAA", "date": "2026-08-21", "action": "dividend"}]
    assert list(source_authority.CanonicalSourceFetch(_fetch(actions))(
        sharadar.ACTIONS)) == actions


def _ticker(permaticker, ticker, category, first="2026-08-21",
            last="2026-08-21"):
    return {"table": "SEP", "permaticker": str(permaticker),
            "ticker": ticker, "category": category,
            "firstpricedate": first, "lastpricedate": last}


def test_seed_coverage_requires_exact_common_equity_and_accounts_ineligible(
        monkeypatch):
    common = "Domestic Common Stock"
    warrant = "Domestic Warrant"
    projection = source_authority.SeedListingProjection([
        _ticker("1", "AAA", common), _ticker("2", "AAAW", warrant),
    ], source_digest="a" * 64)
    monkeypatch.setattr(source_authority.coverage.calendar,
                        "sessions_in_range", lambda start, end: ["2026-08-21"])

    missing = source_authority.SeedCoverageAccumulator(
        projection, lambda ticker, session: "1" if ticker == "AAA" else "2",
        exceptions={})
    try:
        with pytest.raises(source_authority.SourceAuthorityRefused) as caught:
            missing.require_complete(
                date_from="2026-08-21", date_to="2026-08-21")
        evidence = json.loads(str(caught.value).split(": ", 1)[1])
        assert evidence["missing_eligible_total"] == 1
        assert evidence["missing_ineligible_by_category"] == {warrant: 1}
    finally:
        missing.close()

    complete = source_authority.SeedCoverageAccumulator(
        projection, lambda ticker, session: "1", exceptions={})
    try:
        complete.add(_sep("AAA"))
        complete.require_complete(
            date_from="2026-08-21", date_to="2026-08-21")
    finally:
        complete.close()


class _Cursor:
    def __init__(self, row): self.row = row
    def __enter__(self): return self
    def __exit__(self, *args): return None
    def execute(self, sql, params): self.sql, self.params = sql, params
    def fetchone(self): return self.row


class _Conn:
    def cursor(self): return _Cursor(("2026-08-21", "AAA", 2))


def test_staging_preflight_refuses_duplicate_before_streaming():
    with pytest.raises(staging.StagingCanonicalKeyConflict,
                       match="multiplicity"):
        staging._assert_unique_scope(_Conn(), run_id="run", chunk="year")
