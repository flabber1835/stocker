"""Historical readiness remains compact across new and interrupted transitions."""
import pytest

from sentinel import rolling_recovery as recovery, rolling_authority as authority
from sentinel import rolling_daily_checkpoint as checkpoint, rolling_checkpoint as origin
from sentinel import shadow_observation as shadow
from tests.sentinel.test_rolling_recovery import (
    advance, clock, refresh, OBS, conn, pg, source, operational_source,
    issuer_source, dated_source, ready, published)
from tests.sentinel.test_rolling_report_consumers import forbid_materialization

__all__ = ['conn', 'pg', 'source', 'operational_source', 'issuer_source', 'dated_source', 'ready', 'published']


@pytest.mark.parametrize('trailing', [False, True])
def test_recovery_gates_do_not_materialize_warmup(conn, published, dated_source, monkeypatch, trailing):
    advance(conn)
    genesis = origin.read(conn).genesis_sha256
    conn.rollback()
    refresh(conn, dated_source, monkeypatch)
    clock(monkeypatch, '2026-09-16')
    if trailing:
        append = authority.append
        def interrupted(*_args):
            raise OSError('receipt interruption')
        monkeypatch.setattr(authority, 'append', interrupted)
        with pytest.raises(OSError, match='receipt interruption'):
            recovery.advance_one(conn, through='2026-09-15', observation_id=OBS, starting_cash=100_000)
        retained = checkpoint.read(conn)
        conn.rollback()
        monkeypatch.setattr(authority, 'append', append)
        def no_replay(*_args, **_kwargs):
            pytest.fail('committed recovery candidate transitioned twice')
        monkeypatch.setattr(recovery.daily, 'commit_next', no_replay)
    forbid_materialization(monkeypatch)
    result = recovery.advance_one(conn, through='2026-09-15', observation_id=OBS, starting_cash=100_000)
    assert result.session == '2026-09-15'
    assert result.verification == shadow.CANDIDATE
    assert result.shadow_verdict == shadow.NOT_DEPLOYABLE
    assert result.verification_scope == 'ROLLING_RECONSTRUCTION_ONLY'
    assert origin.read(conn).genesis_sha256 == genesis
    if trailing:
        assert result.state.state_hash == retained.state_sha256
    conn.rollback()
    again = recovery.advance_one(conn, through='2026-09-15', observation_id=OBS, starting_cash=100_000)
    assert again.state.state_hash == result.state.state_hash
    assert again.runtime_authority_sha256 == result.runtime_authority_sha256
    for table in ('sentinel_commands', 'sentinel_fills'):
        assert conn.execute('SELECT COUNT(*) FROM '+table).fetchone()[0] == 0
