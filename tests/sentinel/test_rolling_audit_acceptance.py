"""Positive acceptance of rounded presentation scales and dated identity changes."""
from decimal import Decimal

import pytest

from sentinel.core import rolling_continuity
from sentinel.feed import operational_snapshot as op
from tests.sentinel.test_rolling_daily import (
    first, ready, conn, pg, source, operational_source, refresh, advance, resume)


@pytest.mark.parametrize('factor', ['0.5', '0.997123'])
def test_source_rounded_common_benchmark_scale_advances(conn, first, operational_source, monkeypatch, factor):
    for row in operational_source['SFP']:
        if row['ticker'] == 'SPY':
            row['closeadj'] = str((Decimal(row['closeadj']) * Decimal(factor)).quantize(Decimal('.0001')))
    refresh(conn, operational_source, monkeypatch)
    result = advance(conn)
    assert result.session > first.session
    assert resume(conn).state.state_hash == result.state.state_hash


def test_nonuniform_change_outside_source_precision_refuses():
    scales = {}
    rolling_continuity._intersect_scale(scales, 'SEC', '100', '100', 'NONUNIFORM:')
    with pytest.raises(rolling_continuity.RollingContinuityRefused, match='NONUNIFORM'):
        rolling_continuity._intersect_scale(scales, 'SEC', '101', '100', 'NONUNIFORM:')


def test_current_dated_rename_advances_same_security(conn, first, operational_source, monkeypatch):
    original = op.prepare
    data = operational_source
    def renamed(*args, **kwargs):
        today = max(row['date'] for row in data['SEP'])
        for row in data['SEP']:
            if row['ticker'] == 'BBB' and row['date'] == today:
                row['ticker'] = 'NEW'
        for row in data['TICKERS']:
            if row['ticker'] == 'BBB':
                row['ticker'] = 'NEW'
        for kind, contra in [('tickerchangefrom', 'BBB'), ('tickerchangeto', 'NEW')]:
            data['ACTIONS'].append(dict(ticker='NEW', date=today, action=kind,
                name='Same economic issuer', value=None, contraticker=contra, contraname=None))
        return original(*args, **kwargs)
    monkeypatch.setattr(op, 'prepare', renamed)
    refresh(conn, data, monkeypatch)
    result = advance(conn)
    assert result.session > first.session
    assert resume(conn).state.state_hash == result.state.state_hash

__all__ = ['conn', 'first', 'operational_source', 'pg', 'ready', 'source']
