"""Observed source anomaly, synthetic unaffected controls, unchanged prototype."""
import pytest

from sentinel.feed.calendar import sessions_in_range
from research.data_available.observed_go import (
    held_gap, identity, load_fixture, renamed, replay, snapshot_case)


def test_observed_identity_rejection_and_listing_age():
    fixture = load_fixture()
    projection = identity(fixture)
    expected = fixture['bundle']['source_coverage']['identity_diagnostics']
    assert projection.rejections == expected['rejections']
    resolver = projection.resolver()
    for row in fixture['probe']['tickers']['rows']:
        assert resolver.resolve(row['ticker'], '2026-09-24') == str(row['permaticker'])
        assert len(sessions_in_range(row['firstpricedate'], '2026-09-29')) < 127


@pytest.mark.parametrize('rename', [False, True])
def test_observed_unheld_anomaly_leaves_real_orders_and_accounting_unchanged(rename):
    fixture = load_fixture()
    replay(renamed(fixture) if rename else fixture)


@pytest.mark.parametrize('rename', [False, True])
def test_observed_gap_in_hypothetical_holding_is_not_silently_ignored(rename):
    fixture = load_fixture()
    held_gap(renamed(fixture) if rename else fixture)


def test_later_observation_does_not_fabricate_missing_history_or_alias_it():
    fixture = load_fixture()
    _, feed, _ = snapshot_case(fixture, '2026-09-29')
    resolver = identity(fixture).resolver()
    for listing in fixture['probe']['tickers']['rows']:
        sid = str(listing['permaticker'])
        source = sorted((r for r in fixture['probe']['sep']['rows']
                         if resolver.resolve(r['ticker'], r['date']) == sid),
                        key=lambda r:r['date'])
        series = feed.series[sid]
        assert series.sessions == [r['date'] for r in source]
        assert series.raw_closes == [r['closeunadj'] for r in source]
        assert series.signal_closes == [r['close'] for r in source]
