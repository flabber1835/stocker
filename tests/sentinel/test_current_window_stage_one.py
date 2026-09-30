"""Independent economics, real restore and absence recovery for CURRENT_WINDOW_V1."""
from copy import deepcopy
from decimal import Decimal as D
import math
from pathlib import Path
import statistics

import pytest

from sentinel import rolling_runtime, restore_validation
from sentinel.core import window_policy
from sentinel.feed import calendar, runtime_schema, store
from sentinel.strategy import production_strategy
from stock_strategy_shared.wealth_core.feed import SecurityMeta, SecuritySeries, VendorBar
from stock_strategy_shared.wealth_core.window_signals import feature
from tests.sentinel.test_current_window_production import ready  # noqa: F401
from tests.sentinel.test_operational_snapshot import operational_source  # noqa: F401
from tests.sentinel.test_rolling_snapshot_publisher import conn, pg, source  # noqa: F401
from tests.sentinel.test_rolling_daily import refresh, OBS
from tests.sentinel import test_rolling_recovery as recovery_checks


@pytest.mark.parametrize('seed', range(12))
def test_signal_values_match_independent_math_and_ignore_old_candidate_tail(seed):
    days = calendar.previous_sessions('2026-09-14', 300)
    closes = [100*math.exp(.001*i + .015*math.sin(i*(.17+seed*.003))) for i in range(300)]
    meta = SecurityMeta('1', 'ABC', 'Domestic Common Stock', '1', first_session=days[0])
    series = SecuritySeries('1', 'ABC', 'SID:1')
    for i, day in enumerate(days):
        series.append(VendorBar(day, '1', 'ABC', closes[i]*3, closes[i]*3, 1e6,
                                signal_close=closes[i]), i, published_signal=True)
    actual = feature(series, meta, index=299, session=days[-1])
    formation = closes[173:279]
    returns = [math.log(b)-math.log(a) for a, b in zip(formation, formation[1:])]
    momentum = closes[278]/closes[173]-1
    recent = closes[299]/closes[278]-1
    volatility = statistics.stdev(returns)*math.sqrt(252)
    expected = (momentum, recent, volatility, math.log(closes[278]/closes[173])/volatility)
    assert actual.eligible
    assert actual.certified_signals == pytest.approx(expected, rel=1e-10, abs=1e-12)
    series.signal_closes[:173] = [1e6]*173
    assert feature(series, meta, index=299, session=days[-1]) == actual
    # Liquidity belongs to raw traded dollars, not the adjusted signal domain.
    series.raw_closes[-1] = .99
    assert not feature(series, meta, index=299, session=days[-1]).eligible


@pytest.fixture
def dated_source(operational_source, monkeypatch):
    return recovery_checks.dated_source.__wrapped__(operational_source, monkeypatch)


@pytest.fixture
def published(dated_source, ready):
    assert window_policy.enabled(production_strategy()[1])
    return ready


@pytest.mark.parametrize('stop_shock', [False, True])
def test_current_window_absence_equals_uninterrupted_book(conn, pg, published, dated_source, monkeypatch, stop_shock):
    recovery_checks.test_interrupted_book_matches_continuous_production_run(
        conn, pg, published, dated_source, monkeypatch, stop_shock)


@pytest.mark.parametrize('failure', ['candidate', 'receipt'])
def test_current_window_recovery_crash_does_not_repeat_fills(conn, published, dated_source, monkeypatch, failure):
    recovery_checks.test_recovery_crash_keeps_exact_candidate_without_retransition(
        conn, published, dated_source, monkeypatch, failure)


def close_to(actual, expected):
    assert abs(D(str(actual))-expected) < D('0.00000001'), (actual, expected)


def funded_oracle(state, pending, rows):
    """Read raw prices and dollar intents; do not call production accounting."""
    prices = {sid: (D(str(opened)), D(str(closed))) for sid, opened, closed in rows}
    intents = {p['security_id']: D(str(p['intended_dollars'])) for p in pending}
    cash = D(50000)
    shares = {}
    for event in state['ledger']['events']:
        assert event['event_type'] == 'BUY' and event['session'] == '2026-09-15'
        sid = event['security_id']
        opened = prices[sid][0]
        quantity = min(int(intents[sid]/(opened*D('1.001'))), int(cash/(opened*D('1.001'))))
        assert quantity > 0 and D(str(event['shares_delta'])) == quantity
        fee = opened*quantity*D('.001')
        close_to(event['price'], opened)
        close_to(event['fees'], fee)
        close_to(event['cash_before'], cash)
        cash -= opened*quantity + fee
        close_to(event['cash_after'], cash)
        shares[sid] = quantity
    assert len(shares) == 20 and cash >= 0
    assert shares == {e['security_id']: e['current_shares'] for e in state['wealth_core']['episodes'].values()}
    close_to(state['wealth_core']['cash'], cash)
    nav = cash + sum((quantity*prices[sid][1] for sid, quantity in shares.items()), D(0))
    close_to(state['shadow_nav_history'][-1], nav)
    return cash, nav


def test_funded_cash_oracle_and_physical_restore_continue_same_book(conn, ready, operational_source, monkeypatch):
    from tests.support.postgres import _EphemeralPostgres, _find_pg_bin, _run, _as_pg_user
    import os
    import shutil
    monkeypatch.setattr(restore_validation.feed_store, 'require_feed_schema', runtime_schema.require_feed_schema)
    first = rolling_runtime.advance(conn, through='2026-09-14', observation_id=OBS, starting_cash=50000)
    assert first.state.wealth_core['cash'] == 50000 and not first.state.ledger['events']
    refresh(conn, operational_source, monkeypatch)
    second = rolling_runtime.advance(conn, through='2026-09-15', observation_id=OBS, starting_cash=50000)
    binding = conn.execute('SELECT candidate_id FROM sentinel_operational_snapshots ORDER BY publication_version DESC LIMIT 1').fetchone()[0]
    rows = conn.execute('SELECT security_id,open_unadjusted,close_unadjusted FROM sentinel_snapshot_bars '
                        'WHERE candidate_id=%s AND session=%s', (binding, second.session)).fetchall()
    original = second.state.to_dict()
    cash, nav = funded_oracle(original, first.state.pending, rows)
    allocation = D(str(first.state.last_decision['target_core_exposure']))
    bil_open, bil_close = conn.execute('SELECT bil_open_signal,bil_close_signal '
        'FROM sentinel_snapshot_benchmarks WHERE candidate_id=%s AND session=%s',
        (binding, second.session)).fetchone()
    bil_return = D(str(bil_close))/D(str(bil_open))-1
    expected_strategy_nav = (D(50000) + allocation*(nav-D(50000))
        + (1-allocation)*D(50000)*bil_return) * (1-(1-allocation)*D('.001'))
    close_to(second.strategy_nav, expected_strategy_nav)
    for defect in ('cash', 'shares', 'fees'):
        broken = deepcopy(original)
        if defect == 'cash':
            broken['wealth_core']['cash'] += 1
        elif defect == 'shares':
            next(iter(broken['wealth_core']['episodes'].values()))['current_shares'] += 1
        else:
            broken['ledger']['events'][0]['fees'] += 1
        with pytest.raises(AssertionError):
            funded_oracle(broken, first.state.pending, rows)
    conn.commit()
    restored_pg = _EphemeralPostgres()
    try:
        if os.geteuid() == 0:
            shutil.chown(restored_pg.datadir, user='postgres', group='postgres')
        for command in (
            ['pg_basebackup', '-d', conn.info.dsn, '-D', restored_pg.datadir, '-X', 'stream', '-c', 'fast'],
            ['pg_verifybackup', restored_pg.datadir],
            ['pg_ctl', '-D', restored_pg.datadir, '-o', f'-p {restored_pg.port} -h 127.0.0.1 -k {restored_pg.datadir}',
             '-l', str(Path(restored_pg.datadir)/'restored.log'), '-w', 'start']):
            outcome = _run(_as_pg_user([_find_pg_bin(command[0]), *command[1:]]))
            assert outcome.returncode == 0, outcome.stderr
        restored_pg._started = True
        dsn = restored_pg.sync_dsn.rsplit('/', 1)[0] + '/' + conn.info.dbname
        with store.connect(dsn) as restored:
            report = restore_validation.validate_restored_database(restored)
            assert report['transaction_read_only'] and report['restart_state_present']
            restored.rollback()
            resumed = rolling_runtime.status(restored, observation_id=OBS, starting_cash=50000)
            assert resumed.state.state_hash == second.state.state_hash
        # Restore inspection deliberately makes its connection read-only.
        # Runtime continuation owns a separate writable connection.
        with store.connect(dsn) as restored:
            refresh(restored, operational_source, monkeypatch)
            third = rolling_runtime.advance(restored, through='2026-09-16', observation_id=OBS, starting_cash=50000)
            assert {k: (e['security_id'], e['current_shares'])
                    for k, e in third.state.wealth_core['episodes'].items()} == {
                    k: (e['security_id'], e['current_shares'])
                    for k, e in second.state.wealth_core['episodes'].items()}
            close_to(third.state.wealth_core['cash'], cash)
            close_to(third.state.shadow_nav_history[-1], nav)
            from sentinel import rolling_daily_checkpoint
            import json
            restored.execute("UPDATE sentinel_processed_sessions SET state=jsonb_set(state,"
                "'{window_features,prior_state_sha256}',%s::jsonb) WHERE cursor_name=%s",
                (json.dumps('f'*64), rolling_daily_checkpoint.input_name(OBS, third.session)))
            restored.commit()
            with pytest.raises(RuntimeError, match='DAILY_INPUT_ARCHIVE_CHANGED'):
                restore_validation.validate_restored_database(restored)
            restored.rollback()
        from sentinel import rolling_daily
        # The source cluster now trails the simulated clock by one session;
        # check its retained state without claiming fresh execution authority.
        assert rolling_daily.resume(conn, observation_id=OBS, starting_cash=50000).state.state_hash == second.state.state_hash
    finally:
        restored_pg.stop()
