"""Reopen independent transactions against privately published Alpaca material."""
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from sentinel import opening_prewarm, prepared_opening_material as material, schema
from sentinel.execution import feed_inputs
from sentinel.feed import rolling_go_inputs, rolling_store, store
from tests.sentinel.test_publication_read_cost import _substitute_block, alpaca_path, conn, pg, published  # noqa: F401


def install_financial_tables(conn):
    names = ('sentinel_account_binding', 'sentinel_processed_sessions', 'sentinel_rollout_state',
             'sentinel_execution_plans', 'sentinel_commands', 'sentinel_fills')
    for statement in schema.DDL:
        if any('CREATE TABLE IF NOT EXISTS '+name+' (' in statement for name in names):
            conn.execute(statement)
    conn.commit()


@pytest.fixture
def cycle(monkeypatch):
    monkeypatch.setenv('SENTINEL_IMAGE_SOURCE_REVISION', 'a' * 40)
    monkeypatch.setenv('SENTINEL_RUNTIME_IMAGE_DIGEST', 'sha256:' + 'b' * 64)
    monkeypatch.setenv('SENTINEL_PUBLICATION_RECEIPT_KEY', 'private-opening-key-' * 2)
    return SimpleNamespace(**{name: name for name in material._SCOPE_FIELDS})


def test_first_callback_reuses_preparation_full_scan_and_rejects_changed_block(
        conn, published, cycle, tmp_path, monkeypatch):
    # Publication signatures must keep the producer's exact key.
    monkeypatch.setenv('SENTINEL_PUBLICATION_RECEIPT_KEY', 'private-read-cost-test-key-' * 2)
    scans = []
    full = rolling_store._verify_content_uncached
    def scan(*args):
        scans.append(args[1])
        return full(*args)
    monkeypatch.setattr(rolling_store, '_verify_content_uncached', scan)
    def run():
        with material.cycle(cycle, directory=tmp_path), store.connect(conn.info.dsn) as reader:
            with feed_inputs.pinned(reader, commit=False):
                result = rolling_go_inputs.readiness(reader)
                rolling_store.verify_content(reader, published['candidate_id'])
                return result
    first = run()
    assert first.ready and run().checks == first.checks and len(scans) == 1
    proof = tmp_path / 'prepared-opening-snapshot.json'
    previous = proof.read_bytes()
    _substitute_block(conn, published['candidate_id'])
    for attempts in (2, 3):
        with pytest.raises(rolling_store.SnapshotStorageRefused, match='content differs'):
            run()
        assert len(scans) == attempts
        assert proof.read_bytes() == previous


def test_committed_strategy_input_change_and_foreign_broker_lineage(conn, published, cycle, tmp_path, monkeypatch):
    monkeypatch.setenv('SENTINEL_PUBLICATION_RECEIPT_KEY', 'private-read-cost-test-key-' * 2)
    install_financial_tables(conn)
    conn.execute("INSERT INTO sentinel_processed_sessions(cursor_name,session,state) "
                 "VALUES ('rolling-unit','2026-09-14','{}'), ('broker-observation:v4:test','2026-09-14','{}')")
    conn.commit()
    calls = []
    def run():
        with material.cycle(cycle, directory=tmp_path), store.connect(conn.info.dsn) as reader:
            with feed_inputs.pinned(reader, commit=False):
                def read():
                    calls.append(True)
                    return reader.execute("SELECT state FROM sentinel_processed_sessions "
                                           "WHERE cursor_name='rolling-unit'").fetchone()[0]
                return material._measure('test-strategy', lambda: material._checkpoint_witness(reader, {}),
                                         read, dict, dict)
    assert run() == run() == {} and len(calls) == 1
    conn.execute("UPDATE sentinel_processed_sessions SET state='{\"irrelevant\":true}' WHERE cursor_name LIKE 'broker-%'")
    conn.commit()
    assert run() == {} and len(calls) == 1
    conn.execute("UPDATE sentinel_processed_sessions SET state='{\"new\":true}' WHERE cursor_name='rolling-unit'")
    conn.commit()
    assert run() == {'new': True} and len(calls) == 2
    conn.execute("UPDATE sentinel_processed_sessions SET state='{\"wealth_core\":{}}' WHERE cursor_name LIKE 'broker-%'")
    conn.commit()
    assert run() == run() == {'new': True} and len(calls) == 4


def test_handoff_binds_signature_cycle_configuration_and_runtime(cycle, tmp_path, monkeypatch):
    calls = []
    def run():
        with material.cycle(cycle, directory=tmp_path):
            return material._measure('test', lambda: 'same-data', lambda: calls.append(1) or {'value': len(calls)},
                                     dict, dict)
    assert run() == run() == {'value': 1}
    path = tmp_path / 'prepared-opening-test.json'
    header, payload = path.read_bytes().split(b'\n')
    path.write_bytes(header + b'\n' + payload.replace(b'1', b'9'))
    assert run() == {'value': 2}
    cycle.control_generation = 'next'
    assert run() == {'value': 3}
    monkeypatch.setenv('SENTINEL_RUNTIME_IMAGE_DIGEST', 'sha256:'+'c'*64)
    assert run() == {'value': 4}
    monkeypatch.setenv('SENTINEL_PUBLICATION_RECEIPT_KEY', 'a-different-private-key'*2)
    assert run() == {'value': 5}
    header, sig = json.loads(path.read_bytes().split(b'\n')[0])
    header['purpose'] = 'different'
    path.write_bytes(json.dumps([header, material.receipt_authentication.sign(header)]).encode()+b'\n'+b'{"value":5}')
    assert run() == {'value': 6}


def test_startup_only_warms_a_waiting_plan_away_from_open_and_reaps_it(monkeypatch):
    now = datetime.now(timezone.utc)
    cycle = SimpleNamespace(state=SimpleNamespace(value='WAITING_OPEN'), historical_state_only=False,
        plan_id='plan', cycle_id='cycle', execute_at=now+timedelta(seconds=60))
    runtime = SimpleNamespace(_operational_source_only=True, _dual_run_enabled=True,
                              service=SimpleNamespace(_idle_cycle_proof=('owned', cycle)))
    events = []
    exit_status = [None]
    process = SimpleNamespace(poll=lambda: exit_status[0], kill=lambda: events.append('killed'))
    monkeypatch.setattr(opening_prewarm.subprocess, 'Popen', lambda argv, **kwargs: events.append(argv[-1]) or process)
    opening_prewarm.start(runtime, now)
    assert events == []
    cycle.execute_at += timedelta(minutes=10)
    opening_prewarm.start(runtime, now)
    opening_prewarm.start(runtime, now)
    opening_prewarm.stop(runtime)
    assert events == ['cycle', 'killed'] and runtime._opening_warm_process is process
    runtime._opening_warm_attempted = False
    opening_prewarm.start(runtime, now)
    assert events == ['cycle', 'killed']
    exit_status[0] = -9
    opening_prewarm.stop(runtime)
    assert runtime._opening_warm_process is None


def test_ordinary_first_rederivation_and_mutated_account_sizing(conn, published, cycle, tmp_path, monkeypatch):
    from sentinel import dual_plan_authority as sizing
    from tests.sentinel.test_dual_plan_scalar_proof import canonical_authority
    monkeypatch.setenv('SENTINEL_PUBLICATION_RECEIPT_KEY', 'private-read-cost-test-key-' * 2)
    install_financial_tables(conn)
    plan, binding, rollout, shadow, _ = canonical_authority(conn, '100000.125')
    calls = []
    full = sizing._rederive_plan
    def canonical(*args, **kwargs):
        calls.append(True)
        return full(*args, **kwargs)
    monkeypatch.setattr(sizing, '_rederive_plan', canonical)
    def run():
        with material.cycle(cycle, directory=tmp_path), store.connect(conn.info.dsn) as reader:
            with feed_inputs.pinned(reader, commit=False):
                return sizing.rederive_plan(reader, plan=plan, binding=binding, rollout_state=rollout,
                                            expected_shadow_result=shadow)
    assert run() == run() and len(calls) == 1
    assert (tmp_path / 'prepared-opening-sizing.json').is_file()
    conn.execute("UPDATE sentinel_processed_sessions SET state=jsonb_set(state,'{marks,SEC-AAA}','\"1\"') "
                 "WHERE cursor_name=%s", (sizing.CURSOR_PREFIX + plan.plan_id,))
    conn.commit()
    with pytest.raises(sizing.DualPlanAuthorityRefused, match='digest does not match'):
        run()
    assert len(calls) == 2


def test_removed_signature_guard_returns_stale_amount_in_executed_falsifier(cycle, tmp_path, monkeypatch):
    def check():
        with material.cycle(cycle, directory=tmp_path):
            current = ['first']
            loader = lambda: {'amount': current[0]}
            assert material._measure('falsifier', lambda: current[0], loader, dict, dict) == {'amount': 'first'}
            # Copy the signed, old payload into a header for a different subject.
            path = tmp_path / 'prepared-opening-falsifier.json'
            first, data = path.read_bytes().split(b'\n', 1)
            header, signature = json.loads(first)
            current[0] = 'second'
            header['subject'] = material.digest([material._active.get()[1], 'falsifier', 'second'])
            path.write_bytes(json.dumps([header, signature]).encode() + b'\n' + data)
            result = material._measure('falsifier', lambda: current[0], loader, dict, dict)
            assert result == {'amount': 'second'}, 'stale material crossed a changed subject'
    check()
    monkeypatch.setattr(material.hmac, 'compare_digest', lambda a,b: True)
    with pytest.raises(AssertionError, match='stale material crossed'):
        check()


def test_visibility_changes_invalidate_old_material(conn, cycle, tmp_path):
    conn.execute('CREATE ROLE opening_qualification_reader NOLOGIN')
    conn.commit()
    calls = []
    def measure():
        with material.cycle(cycle, directory=tmp_path):
            return material._measure('role', lambda: material.version_epoch(conn, ()),
                                     lambda: calls.append(True) or {'count': len(calls)}, dict, dict)
    def count():
        return measure()['count']
    assert count() == count() == 1
    conn.execute('SET LOCAL ROLE opening_qualification_reader')
    assert count() == count() == 2
    conn.rollback()
    conn.execute('SET LOCAL SESSION AUTHORIZATION opening_qualification_reader')
    assert count() == 3  # Equal effective role, different login role.
    conn.rollback()
    conn.execute('SET LOCAL row_security=off')
    assert count() == 4
    conn.execute('SET LOCAL search_path=public')
    assert count() == 5
    xmax = int(conn.execute('SELECT pg_snapshot_xmax(pg_current_snapshot())::text').fetchone()[0])
    assert material.version_epoch(conn, [(str((xmax + 20) % 2**32), '(1,1)')]) is None


def test_prewarm_passes_only_exact_parked_plan_to_canonical_reader(conn, published, cycle, tmp_path, monkeypatch):
    from sentinel import dual_reconciliation, snapshot_scan_admission
    from sentinel.automation import store as scheduler
    from sentinel.execution import journal
    from sentinel.feed import readiness_scope
    monkeypatch.setenv('SENTINEL_PUBLICATION_RECEIPT_KEY', 'private-read-cost-test-key-' * 2)
    monkeypatch.setattr(material, 'gettempdir', lambda: str(tmp_path))
    cycle.state = SimpleNamespace(value='WAITING_OPEN')
    cycle.historical_state_only = False
    cycle.plan_id, cycle.plan_fingerprint = 'parked', 'expected'
    cycle.execute_at = datetime.now(timezone.utc) + timedelta(minutes=8)
    plan = SimpleNamespace(plan_id='parked', fingerprint=lambda: 'other')
    monkeypatch.setattr(scheduler, 'load_cycle', lambda conn, key: cycle)
    monkeypatch.setattr(journal, 'latest_plan', lambda conn: plan)
    alarms, calls = [], []
    monkeypatch.setattr(opening_prewarm.signal, 'alarm', alarms.append)
    def verify(reader, **kwargs):
        assert reader.execute('SHOW transaction_read_only').fetchone() == ('on',)
        assert snapshot_scan_admission._background.get()
        assert material.active() and readiness_scope.capture(reader) is not None
        calls.append(kwargs)
    monkeypatch.setattr(dual_reconciliation, 'require_plan_matches_verified_shadow', verify)
    def run():
        with store.connect(conn.info.dsn) as reader:
            reader.read_only = True
            opening_prewarm.verify_waiting(reader, cycle_id=cycle.cycle_id,
                observation_id='primary', starting_cash='50000')
    run()
    assert not calls
    plan.fingerprint = lambda: 'expected'
    run()
    assert calls == [dict(plan=plan, observation_id='primary', starting_cash='50000')]
    assert alarms == [240, 240]


def test_restart_reads_typed_shadow_state_and_still_checks_present_process(conn, published, cycle, tmp_path, monkeypatch):
    from sentinel import runtime_admission, rolling_runtime, rolling_authority, shadow_observation
    from tests.v5.test_opening import case
    monkeypatch.setenv('SENTINEL_PUBLICATION_RECEIPT_KEY', 'private-read-cost-test-key-' * 2)
    install_financial_tables(conn)
    state, _ = case()
    context = dict(runtime={'release': 'current'}, controller=SimpleNamespace(to_dict=lambda: {'code': 'v1'}))
    result = shadow_observation.ShadowObservationResult('2026-09-14', state, 'b'*64, '1', '2', '1', '2', 'a'*64)
    authority = rolling_authority.Authority(observation_id='test', session=result.session, timing={}, pitr={},
        previous_authority_sha256=None, previous_record_sha256=None, **{field: 'c'*64 for field in
        ('checkpoint_sha256','record_sha256','state_sha256','input_sha256','runtime_sha256','publication_sha256','readiness_sha256')})
    loaded, process = [], []
    monkeypatch.setattr(runtime_admission, 'require_retained_process', lambda *args: process.append(True))
    def run():
        with material.cycle(cycle, directory=tmp_path), store.connect(conn.info.dsn) as reader:
            with feed_inputs.pinned(reader, commit=False) as pub:
                def canonical():
                    loaded.append(True)
                    return (rolling_runtime._StatusBinding(result.session, pub.to_dict(), {}, state.state_hash,
                                                           context['runtime']), None, result, authority, None)
                return material.shadow(reader, context, canonical)
    original = run()
    reused = run()
    assert reused[0] == original[0] and reused[3] == authority
    assert reused[2].state.state_hash == state.state_hash and reused[2].state is not state
    assert loaded == [True] and process == [True]
