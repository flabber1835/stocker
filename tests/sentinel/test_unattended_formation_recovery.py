"""Actual provider publication and canonical state through restart boundaries."""
from datetime import timedelta
import json

import pytest

from sentinel import formation_cache, rolling_initialization as initial, rolling_runtime
from sentinel import rolling_recovery, rolling_authority, rolling_checkpoint
from sentinel.core import formation_preview
from sentinel.core.formation import Formation
from sentinel.core.formation_inputs import FormationInputs
from sentinel.feed import calendar, operational_snapshot as snapshots
from sentinel.feed.rolling_contract import PriceWindow
from sentinel.strategy import production_strategy
from tests.sentinel.test_alpaca_daily_formation import provider, OBS  # noqa: F401
from tests.sentinel.test_rolling_snapshot_publisher import conn, pg  # noqa: F401


def test_authenticated_preview_cache_avoids_replay_in_initialization(conn, provider, monkeypatch, tmp_path):
    _, publish = provider
    binding = publish()
    monkeypatch.setenv('SENTINEL_STATE_DIR', str(tmp_path))
    strategy = production_strategy()[1]
    transitions = []
    original = Formation.advance
    def counted(formed, published):
        transitions.append(published.session)
        return original(formed, published)
    monkeypatch.setattr(Formation, 'advance', counted)
    with snapshots.pinned(conn) as (pub, _):
        source = FormationInputs(conn, binding, pub)
        expected = formation_preview.run(source, capital=50_000, strategy=strategy, data_version=pub.version)
        assert len(transitions) == 126
        repeated = formation_preview.run(FormationInputs(conn, binding, pub),
            capital=50_000, strategy=strategy, data_version=pub.version)
        assert expected[0].to_dict() == repeated[0].to_dict() and expected[1:] == repeated[1:]
        assert len(transitions) == 126
        plan = source.plan(capital=50_000, strategy=strategy)
        path, _ = formation_cache.location(plan)
        other = source.plan(capital=49_000, strategy=strategy)
        assert formation_cache.location(other)[0] != path
        assert formation_cache.load(formation_cache.location(other), other) is None
    first = initial.initialize(conn, observation_id=OBS, starting_cash=50_000)
    assert len(transitions) == 126
    assert initial.resume(conn, observation_id=OBS, starting_cash=50_000).state.state_hash == first.state.state_hash
    assert conn.execute('SELECT COUNT(*) FROM sentinel_commands').fetchone()[0] == 0
    # A recomputed outer encoding still cannot promote an unauthenticated state.
    value = json.loads(path.read_text())
    value['hmac_sha256'] = '0'*64
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match='AUTHENTICATION'):
        formation_cache.load(formation_cache.location(plan), plan)
    assert formation_cache.reusable(formation_cache.location(plan), plan) is None
    # Financial database progress remains the primary authority, independent
    # of the damaged disposable calculation file.
    assert initial.resume(conn, observation_id=OBS, starting_cash=50_000).state.state_hash == first.state.state_hash


def test_midday_origin_commits_once_without_trading_authority(conn, provider, monkeypatch):
    prices, publish = provider
    publish()
    day = str(prices.window.end)
    opened, _ = calendar.session_window(calendar.next_session(day))
    monkeypatch.setattr(initial, '_now', lambda conn:opened+timedelta(minutes=20))
    result = rolling_runtime.service_advance(conn, through=day, observation_id=OBS, starting_cash=50_000)
    assert result.verification_scope == 'ROLLING_RECONSTRUCTION_ONLY'
    retained = rolling_checkpoint.read(conn)
    conn.rollback()
    assert retained.precommit_timing['status'] == 'STATE_ONLY_AFTER_OPEN'
    from sentinel.rolling_reconstruction_evidence import InputsUnavailable
    with pytest.raises(InputsUnavailable, match='NEXT_FRESH_SESSION_REQUIRED'):
        rolling_runtime.service_advance(conn, through=day, observation_id=OBS, starting_cash=50_000)
    repeated = initial.resume(conn, observation_id=OBS, starting_cash=50_000)
    assert repeated.state.state_hash == result.state.state_hash
    assert conn.execute('SELECT COUNT(*) FROM sentinel_commands').fetchone()[0] == 0
    assert len(rolling_authority.latest(conn, OBS)) == 1
    conn.rollback()


def test_missing_publisher_day_is_acquired_now_without_reset_or_broker_authority(conn, provider, monkeypatch):
    prices, publish = provider
    publish()
    first_day = str(prices.window.end)
    rolling_runtime.advance(conn, through=first_day, observation_id=OBS, starting_cash=50_000)
    genesis = rolling_checkpoint.read(conn).genesis_sha256
    conn.rollback()
    missing = calendar.next_session(first_day)
    prices.window = PriceWindow.through(missing)
    # No publication exists for the missing day. Whole appliance was absent.
    opened, _ = calendar.session_window(calendar.next_session(missing))
    monkeypatch.setattr(initial, '_now', lambda conn:opened+timedelta(minutes=20))
    result = rolling_recovery.advance_one(conn, through=missing, observation_id=OBS, starting_cash=50_000)
    assert result.session == missing and result.state.last_processed_session == missing
    assert result.verification_scope == 'ROLLING_RECONSTRUCTION_ONLY'
    assert rolling_checkpoint.read(conn).genesis_sha256 == genesis
    conn.rollback()
    with snapshots.pinned(conn) as (pub, binding):
        marker = pub.evidence['operational_recovery']
        assert marker['cursor'] == first_day and marker['session'] == missing
        assert marker['historical_availability_claim'] is False and marker['broker_authority'] is False
        observed = conn.execute('SELECT published_at FROM sentinel_corpus_publications WHERE version=%s',
                                (pub.version,)).fetchone()[0]
        assert marker['observed_at'] == observed.isoformat()
    repeated = rolling_recovery.advance_one(conn, through=missing, observation_id=OBS, starting_cash=50_000)
    assert result.state.state_hash == repeated.state.state_hash
    assert conn.execute('SELECT COUNT(*) FROM sentinel_commands').fetchone()[0] == 0
    conn.rollback()
    # A second absent publisher day resumes the same chain, then a genuinely
    # fresh daily publication can regain prospective shadow authority.
    another = calendar.next_session(missing)
    prices.window = PriceWindow.through(another)
    opened, _ = calendar.session_window(calendar.next_session(another))
    monkeypatch.setattr(initial, '_now', lambda conn: opened+timedelta(minutes=20))
    recovered = rolling_recovery.advance_one(conn, through=another, observation_id=OBS, starting_cash=50_000)
    assert recovered.session == another and recovered.verification_scope == 'ROLLING_RECONSTRUCTION_ONLY'
    fresh = calendar.next_session(another)
    prices.window = PriceWindow.through(fresh)
    publish()
    now = calendar.session_window(calendar.next_session(fresh))[0]-timedelta(hours=2)
    monkeypatch.setattr(initial, '_now', lambda conn: now)
    live = rolling_runtime.advance(conn, through=fresh, observation_id=OBS, starting_cash=50_000)
    assert live.session == fresh and live.shadow_verdict == 'SHADOW_GO'
    assert not rolling_runtime.advance(conn, through=fresh, observation_id=OBS, starting_cash=50_000).appended
    assert rolling_checkpoint.read(conn).genesis_sha256 == genesis
    assert conn.execute('SELECT COUNT(*) FROM sentinel_commands').fetchone()[0] == 0
