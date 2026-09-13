"""Source precision cannot authorize a different contractual consolidation."""
from fractions import Fraction
import json

import pytest

from sentinel.feed.domains import NormalisationReport, normalise_sep_rows
from stock_strategy_shared.split_reconciliation import (
    SplitAuthority, SplitStreamReconciler, canonical_split_multiplier, resolve_split_orientation)
from stock_strategy_shared.wealth_core.state import PortfolioState
from stock_strategy_shared.wealth_core.ledger import Ledger
from tests.wealth_core.test_conversion_entitlements import book, bars, step
from tests.sentinel.test_corporate_action_cash_adjudication import pg, conn


@pytest.mark.parametrize("ratio", [1 / 10.89958, .09175, .4, .98456, 1.5])
def test_noninteger_contractual_ratios_are_preserved(ratio):
    assert canonical_split_multiplier(ratio, ratio) == ratio
    assert resolve_split_orientation(ratio, ratio, bounds=(ratio, ratio))[0] == ratio


def test_five_decimal_reconstruction_requires_unique_independent_evidence():
    assert canonical_split_multiplier(.03333, 1 / 30) == 1 / 30
    assert canonical_split_multiplier(.03333) == .03333
    assert canonical_split_multiplier(.03333, .05) == .03333
    assert canonical_split_multiplier(.00001, .00001) == .00001  # many denominators
    assert canonical_split_multiplier(.0333334, 1 / 30) == .0333334  # more precision


@pytest.mark.parametrize("shifted", [False, True])
def test_stream_applies_the_same_noninteger_ratio_on_direct_and_shifted_paths(shifted):
    ratio = 1 / 10.89958
    day = "2026-08-12"
    authority = SplitAuthority({("OLD", day): ratio} if not shifted else {},
        previous_session_candidates={('OLD', day): (('OLD', '2026-08-13'), ratio)} if shifted else {})
    result = SplitStreamReconciler(authority).decide(
        ("OLD", day), prev_close=10., prev_raw=1., close=10., raw=10.89958,
        fallback_ratio=ratio)
    assert result.ratio == ratio


def test_normalizer_to_canonical_split_preserves_issuer_neutral_nav_and_restart():
    ratio = float(Fraction(1) / Fraction("10.89958"))
    report = NormalisationReport()
    rows = [dict(ticker="OLD", date="2026-08-11", open=10., close=10.,
                 closeunadj=1., volume=1e6),
            dict(ticker="OLD", date="2026-08-12", open=10., close=10.,
                 closeunadj=10.89958, volume=1e6)]
    normalized = list(normalise_sep_rows(rows, report=report,
        authoritative_splits={("OLD", "2026-08-12"): ratio}))
    applied = normalized[-1].vendor.split_ratio
    assert applied == ratio and applied != 1 / 11
    state = book([1_089_958])
    result = step(state, Ledger(), daily=bars(old_price=10.89958, split=applied))
    assert state.episodes[0].current_shares == pytest.approx(100_000, abs=1e-8)
    assert result.resolved_open_equity == pytest.approx(1_099_958, abs=1e-8)
    assert PortfolioState.from_dict(json.loads(json.dumps(state.to_dict()))).to_dict() == state.to_dict()


def test_v9_split_history_is_replayed_before_v10_authority_and_survives_restart(conn, pg, monkeypatch):
    from datetime import date
    from sentinel.feed import ingest, maintenance, publication, sharadar, store
    from sentinel.core.history import HistoryReconstructionRequired, require_history_compatible
    from stock_strategy_shared import split_reconciliation as splits
    ratio = 1 / 10.89958
    days = ['2026-08-11', '2026-08-12', '2026-08-13']

    def fetch(table, params=None, **kwargs):
        params = params or {}
        low, high = str(params.get('date.gte', '0000')), str(params.get('date.lte', '9999'))
        if table == sharadar.SEP:
            return [dict(ticker='SMX', date=day, close=10., open=10.,
                         closeunadj=1. if day < days[1] else 10.89958,
                         volume=1e6, lastupdated=day) for day in days if low <= day <= high]
        if table == sharadar.ACTIONS:
            return [dict(ticker='SMX', date=days[1], action='split', value=str(ratio))] \
                if low <= days[1] <= high else []
        if table == sharadar.TICKERS:
            return [dict(permaticker='P:SMX', ticker='SMX', firstpricedate='2020-01-01',
                         category='Domestic Common Stock')]
        return []

    def applied(database):
        with database.cursor() as cur:
            cur.execute("SELECT split_ratio FROM sentinel_bars WHERE ticker='SMX' AND session=%s", (days[1],))
            return cur.fetchone()[0]

    with monkeypatch.context() as legacy:
        legacy.setattr(splits, 'canonical_split_multiplier', lambda value, *args: 1 / 11)
        legacy.setattr(maintenance, 'reconcile_actions_if_due', maintenance._core.reconcile_actions_if_due)
        ingest.seed(conn, date_from=days[0], date_to=days[-1], fetch=fetch)
    prior = publication.require_current(conn)
    assert applied(conn) == 1 / 11
    with store.corpus_write_lock(conn):
        maintenance._core._write_cursor(conn, name='sharadar-actions-export-reconcile:v9',
            kind='sharadar-actions-export-reconcile/v9', through=date.fromisoformat(days[-1]),
            publication_version=prior.version)
        assert maintenance.load_actions_cursor(conn) is None
        maintenance.reconcile_actions_if_due(conn, fetch=fetch, through=days[-1])
    corrected = publication.require_current(conn)
    assert applied(conn) == ratio
    assert corrected.evidence['split_authority'][0]['stated_multiplier'] == str(ratio)
    assert corrected.evidence['affected_action_dates'] == [days[1]]
    with store.connect(pg.sync_dsn) as resumed:
        assert applied(resumed) == ratio
        with store.corpus_write_lock(resumed):
            maintenance.reconcile_actions_if_due(resumed, fetch=fetch, through=days[-1], force=True)
        repeated = publication.require_current(resumed)
        with resumed.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM sentinel_corpus_publications WHERE evidence->>'kind'='actions_economic_semantics_v10'")
            assert cur.fetchone()[0] == 1
        with pytest.raises(HistoryReconstructionRequired):
            require_history_compatible(prior_version=prior.version, last_processed_session=days[-1],
                version=repeated.version, proof=repeated.evidence['strategy_history'])
