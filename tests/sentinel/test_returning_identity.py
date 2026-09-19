"""A known inactive identity can return without inventing formation history."""
from copy import deepcopy

import pytest

from sentinel import rolling_checkpoint as origin
from sentinel.core import rolling_continuity as continuity
from sentinel.core.session import _path_dependent_security_ids
from sentinel.feed import operational_snapshot as op
from tests.sentinel import test_rolling_initialization as initial_fixture
from tests.sentinel.test_rolling_daily import advance, refresh, resume
from tests.sentinel.test_operational_snapshot import operational_source
from tests.sentinel.test_rolling_snapshot_publisher import conn, pg, source


@pytest.fixture
def dormant(conn, operational_source, monkeypatch):
    data = operational_source
    original = op.prepare
    def with_inactive_identity(*args, **kwargs):
        first = min(row['date'] for row in data['SEP'])
        data['TICKERS'].append({**data['TICKERS'][0], 'ticker': 'RETURN', 'permaticker': '999',
                                'lastpricedate': first})
        data['SEP'].append({**data['SEP'][0], 'ticker': 'RETURN', 'date': first})
        return original(*args, **kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(op, 'prepare', with_inactive_identity)
        initial_fixture.ready.__wrapped__(conn, data, patch)
        patch.setattr(op, 'prepare', original)
        # The fixture context owns the reviewed runtime identity and clock.
        first = initial_fixture.start(conn)
        yield first


def returning_snapshot(conn, data, monkeypatch):
    original = op.prepare
    def with_return(*args, **kwargs):
        current = max(row['date'] for row in data['SEP'])
        old = next(row for row in data['TICKERS'] if row['ticker'] == 'RETURN')
        old['lastpricedate'] = min(row['date'] for row in data['SEP'])
        data['TICKERS'].append({**old, 'ticker': 'RETURN2',
                                'firstpricedate': current, 'lastpricedate': current})
        row = next(row for row in data['SEP'] if row['date'] == current)
        data['SEP'].append({**row, 'ticker': 'RETURN2'})
        return original(*args, **kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(op, 'prepare', with_return)
        refresh(conn, data, monkeypatch)


def test_return_restarts_features_without_admission_and_survives_restart(
        conn, dormant, operational_source, monkeypatch):
    assert '999' not in dormant.state.feed['series']
    assert '999' not in _path_dependent_security_ids(dormant.state.wealth_core, dormant.state.pending)
    returning_snapshot(conn, operational_source, monkeypatch)
    with op.pinned(conn) as (_pub, binding):
        refs = continuity.SnapshotReferences(conn, candidate_id=binding['candidate_id'],
                                            snapshot_id=binding['snapshot_id'])
        historical, _ = refs.current_metadata(session=dormant.session)
        assert historical['999'].ticker == 'RETURN'
    result = advance(conn)
    assert result.state.feed['series']['999']['sessions'] == [result.session]
    assert not any(row['security_id'] == '999' for row in result.state.pending)
    assert not any(row['security_id'] == '999' for row in result.state.wealth_core['episodes'].values())
    assert resume(conn).state.state_hash == result.state.state_hash


def test_missing_economic_dependency_anchor_is_not_inactive_reentry(
        conn, dormant, operational_source, monkeypatch):
    returning_snapshot(conn, operational_source, monkeypatch)
    broken = deepcopy(dormant.state)
    broken.wealth_core['security_cooldowns']['999'] = 3
    with op.pinned(conn) as (pub, binding):
        with pytest.raises(continuity.RollingContinuityRefused, match='ANCHOR_REQUIRED'):
            continuity.prepare(conn, prior=broken, previous_binding=origin.read(conn).snapshot,
                               publication=pub, binding=binding)


__all__ = ['conn', 'pg', 'source', 'operational_source']
