"""Real PostgreSQL: aged evidence, controlled deletion and independent recovery."""
from dataclasses import asdict
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from sentinel.execution import feed_actions, feed_inputs, journal, reconcile
from sentinel.execution.feed_cash import SnapshotCashInputs
from sentinel.feed import action_history, calendar, operational_snapshot as op
from sentinel.feed import retention, rolling_store, rolling_jobs as jobs, runtime_schema, store
from sentinel.feed.rolling_contract import PriceWindow
from tests.sentinel.test_operational_snapshot import enqueue, operational_source  # noqa: F401
from tests.sentinel.test_rolling_snapshot_publisher import conn, pg, source  # noqa: F401

__all__ = ['conn', 'pg', 'source', 'operational_source']

MAINTAIN = retention.maintain


def publish(conn):
    return op.prepare(conn, enqueue(conn))


def aged_source(data, monkeypatch, end, *, actions=True):
    window = PriceWindow.through(end)
    first, second = '2024-12-16', '2025-09-15'
    monkeypatch.setattr(op, 'source_final_session', lambda *_: end)
    monkeypatch.setattr(calendar, 'latest_closed_session', lambda *_: end)
    for row in data['TICKERS']:
        row['firstpricedate'], row['lastpricedate'] = '2023-01-03', end
    data['SEP'] = []
    data['SFP'] = []
    for day in window.sessions:
        factor = (2 if str(day) >= first else 1) * (3 if str(day) >= second else 1) if actions else 1
        for symbol in ('AAA', 'BBB'):
            data['SEP'].append(dict(ticker=symbol, date=str(day), open='50', close='50',
                closeunadj=str(Decimal(600) / (factor if symbol == 'AAA' else 1)), volume='10000'))
        for symbol in ('SPY', 'BIL'):
            data['SFP'].append(dict(ticker=symbol, date=str(day), open='51', close='51',
                closeunadj=str(Decimal(306) / factor), closeadj='60'))
    data['ACTIONS'] = [dict(ticker=symbol, date=day, action='split', name='fixture', value=value,
                           contraticker=None, contraname=None)
                       for day, value in ((first, '2'), (second, '3')) if day <= end
                       for symbol in ('AAA', 'BIL')] if actions else []
    # Reference source authority expects a nonempty response. This old relation
    # has no scalar or material effect and lies outside retained coverage.
    data['ACTIONS'].append(dict(ticker='AAA', date='2000-01-03', action='relation', name='fixture',
                               value=None, contraticker='BBB', contraname=None))
    from sentinel.feed.source_authority.corporate_action_data import CASH_ADJUDICATION_AUTHORITIES
    data['ACTIONS'].extend(dict(ticker=r['ticker'], date=r['source_action_date'], action=r['source_action'],
        name='fixture', value=r['stale_source_amount'], contraticker=None, contraname=None)
        for r in CASH_ADJUDICATION_AUTHORITIES if r['source_action_date'] <= end)


@pytest.fixture
def aged(conn, operational_source, monkeypatch):
    for end in ('2025-01-02', '2025-12-01', '2026-09-14'):
        aged_source(operational_source, monkeypatch, end)
        result = publish(conn)
    return result


def test_old_command_and_bil_actions_survive_real_retirement_and_restart(conn, aged):
    import psycopg
    begin, end = date(2024, 12, 13), date(2026, 9, 14)
    lookup = feed_actions.action_lookup(conn, start=begin, end=end)
    assert lookup('1') == lookup('SENTINEL:BIL') == Decimal(6)
    assert lookup('1', since=date(2024, 12, 16)) == Decimal(3)
    assert lookup('1', since=date(2025, 9, 15)) == Decimal(1)
    from sentinel.execution.commands import Command
    from sentinel.execution.identity import CommandIdentity, DeploymentIdentity
    from sentinel.execution.contract import BrokerInstrument, Side
    from sentinel.execution.states import CommandState
    command = Command(identity=CommandIdentity(DeploymentIdentity('retention', 'sim', 'paper', 1), 'old', '1'),
        instrument=BrokerInstrument('1', 'AAA'), side=Side.BUY, quantity=Decimal(10),
        filled_quantity=Decimal(10), state=CommandState.FILLED,
        created_at=datetime(2024, 12, 13, 15, tzinfo=timezone.utc))
    before = asdict(command)
    assert reconcile.expected_book_from_commands([command], lookup) == {'1': Decimal(60)}
    assert asdict(command) == before
    evidence = action_history.records(conn, version=aged['data_version'], start=begin, end=end)
    bil = evidence['2024-12-16']['defensive']
    assert evidence['2024-12-16']['identity_rows'][0]['permaticker'] == '1'
    assert [r[0] for r in bil] == ['2024-12-13', '2024-12-16']
    assert bil[0][2] / bil[1][2] == 2
    assert conn.execute('SELECT count(*) FROM sentinel_snapshot_bars').fetchone()[0] == 600
    assert conn.execute('SELECT count(*) FROM sentinel_snapshot_retirements').fetchone()[0] == 2
    conn.commit()
    with psycopg.connect(conn.info.dsn) as restarted:
        again = feed_actions.action_lookup(restarted, start=begin, end=end)
        assert again.scalar_evidence_for(['1', 'SENTINEL:BIL']) == lookup.scalar_evidence_for(['1', 'SENTINEL:BIL'])
        assert reconcile.expected_book_from_commands([command], again) == {'1': Decimal(60)}


def test_no_action_aging_needs_no_expired_prices(conn, operational_source, monkeypatch):
    for end in ('2025-01-02', '2025-12-01', '2026-09-14'):
        aged_source(operational_source, monkeypatch, end, actions=False)
        publish(conn)
    lookup = feed_actions.action_lookup(conn, start=date(2024, 12, 13), end=date(2026, 9, 14))
    assert lookup('1') == lookup('SENTINEL:BIL') == 1
    assert lookup.scalar_events == lookup.unresolved_events == ()


def test_out_of_window_correction_is_scoped_and_original_evidence_immutable(conn, aged, operational_source):
    before = conn.execute('SELECT payload FROM sentinel_action_history ORDER BY session').fetchall()
    # Both source and current prices remain structurally valid; only an old
    # accepted action outside the price window changes its source terms.
    old = next(r for r in operational_source['ACTIONS'] if r['date'] == '2024-12-16' and r['ticker'] == 'AAA')
    old['value'] = '4'
    publish(conn)
    lookup = feed_actions.action_lookup(conn, start=date(2024, 12, 13), end=date(2026, 9, 14))
    assert lookup('1') == 6
    assert lookup.material_events_for(security_ids=['1'])[0].reason == 'RETAINED_ACTION_MEANING_CHANGED'
    assert lookup.material_events_for(security_ids=['2', 'SENTINEL:BIL']) == ()
    assert conn.execute('SELECT payload FROM sentinel_action_history ORDER BY session').fetchall() == before
    old['value'] = '2'
    publish(conn)
    assert not feed_actions.action_lookup(conn, start=date(2024, 12, 13), end=date(2026, 9, 14)).unresolved_events


def test_retained_cash_reader_supplies_old_entitlement_without_synthetic_cash(conn, operational_source, monkeypatch):
    aged_source(operational_source, monkeypatch, '2025-01-02', actions=False)
    dividend = dict(ticker='AAA', date='2024-12-16', action='dividend', name='fixture', value='1',
                    contraticker=None, contraname=None)
    operational_source['ACTIONS'].append(dividend)
    publish(conn)
    for end in ('2025-12-01', '2026-09-14'):
        aged_source(operational_source, monkeypatch, end, actions=False)
        operational_source['ACTIONS'].append(dividend)
        publish(conn)
    cash = SnapshotCashInputs(conn, feed_inputs.require_current(conn))
    assert '2024-12-16' in cash.days(date(2024, 12, 13), date(2026, 9, 14))
    bars = cash.bars('2024-12-16', ['1'])
    assert bars[0][0] == '1' and bars[0][-1] == 12
    assert cash.actions('2024-12-16', ['AAA'])[0][3] == '1'


def test_atomic_history_and_publication_rollback_then_lost_ack(conn, operational_source, monkeypatch):
    original = op.publication._insert_receipted_publication
    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise OSError('interrupted publication')
    monkeypatch.setattr(op.publication, '_insert_receipted_publication', fail)
    with pytest.raises(OSError, match='interrupted'):
        publish(conn)
    assert conn.execute('SELECT count(*) FROM sentinel_action_history').fetchone()[0] == 0
    assert conn.execute('SELECT count(*) FROM sentinel_action_coverage').fetchone()[0] == 0
    monkeypatch.setattr(op.publication, '_insert_receipted_publication', original)
    result = publish(conn)
    conn.commit()
    assert op.prepare(conn, result['job_id']) == result
    assert conn.execute('SELECT count(*) FROM sentinel_action_coverage').fetchone()[0] == 1


def test_current_generation_cannot_be_retired_even_by_direct_sql(conn, operational_source):
    result = publish(conn)
    conn.commit()
    with pytest.raises(Exception, match='live dependencies'):
        with journal.writer_lock(conn), store.corpus_write_lock(conn):
            conn.execute('INSERT INTO sentinel_snapshot_retirements(candidate_id) VALUES(%s)', (result['candidate_id'],))
    assert len(list(rolling_store.read_bars(conn, result['candidate_id']))) == 600


def test_reader_pin_excludes_cleanup_and_incremental_retry_finishes(conn, operational_source, monkeypatch):
    import psycopg
    monkeypatch.setattr(retention, 'maintain', lambda *_: None)
    first, second = publish(conn), publish(conn)
    conn.commit()
    with psycopg.connect(conn.info.dsn) as reader:
        with op.pinned(reader, commit=False):
            assert MAINTAIN(conn)['status'] == 'RETRY'
            assert len(list(rolling_store.read_bars(reader, first['candidate_id']))) == 600
        reader.rollback()
    step = MAINTAIN(conn, batch_rows=100)
    assert step['deleted_rows'] == 100 and step['more_work']
    for _ in range(9):
        assert MAINTAIN(conn, batch_rows=100)['status'] == 'COMPLETE'
    assert conn.execute('SELECT count(*) FROM sentinel_snapshot_bars WHERE candidate_id=%s', (first['candidate_id'],)).fetchone()[0] == 0
    assert len(list(rolling_store.read_bars(conn, second['candidate_id']))) == 600
    with pytest.raises(rolling_store.SnapshotStorageRefused, match='PAYLOAD_RETIRED'):
        list(rolling_store.read_bars(conn, first['candidate_id']))
    # Immutable identity/receipt survives even after its bulk data is gone.
    assert op.published(conn, first['job_id']) == first


def test_cleanup_rollback_and_failure_do_not_stop_next_publication(conn, operational_source, monkeypatch):
    first = publish(conn)
    original = retention._pass
    def fail(c, **kwargs):
        original(c, **kwargs)
        raise OSError('cleanup interrupted')
    monkeypatch.setattr(retention, '_pass', fail)
    second = publish(conn)
    assert second['data_version'] == 2
    assert len(list(rolling_store.read_bars(conn, first['candidate_id']))) == 600
    assert conn.execute('SELECT diagnostic FROM sentinel_snapshot_maintenance').fetchone()[0]['status'] == 'RETRY'
    conn.commit()
    monkeypatch.setattr(retention, '_pass', original)
    assert MAINTAIN(conn)['deleted_rows'] == 900
    conn.commit()
    assert MAINTAIN(conn)['deleted_rows'] == 0


def test_repeated_publications_bound_bulk_storage_and_preserve_failed_attempts(conn, operational_source):
    first = publish(conn)
    for _ in range(4):
        latest = publish(conn)
    assert conn.execute('SELECT count(*) FROM sentinel_snapshot_bars').fetchone()[0] == 600
    assert conn.execute('SELECT count(*) FROM sentinel_snapshot_jobs').fetchone()[0] == 5
    assert conn.execute('SELECT count(*) FROM sentinel_corpus_publications').fetchone()[0] == 5
    assert latest['data_version'] == 5
    assert op.published(conn, first['job_id']) == first
    runtime_schema.require_feed_schema(conn)


def test_missing_retained_event_cannot_become_no_action(conn, aged):
    conn.execute('SET LOCAL session_replication_role=replica')
    conn.execute("DELETE FROM sentinel_action_history WHERE session='2024-12-16'")
    conn.commit()
    with pytest.raises(ValueError, match='EVIDENCE_CORRUPT'):
        feed_actions.action_lookup(conn, start=date(2024, 12, 13), end=date(2026, 9, 14))


def test_terminal_candidate_cleanup_preserves_job_and_exact_reacquisition(conn, operational_source, monkeypatch):
    from sentinel.feed.rolling_source import SharadarSource
    original = SharadarSource.corroborate
    def fail(*args):
        raise ValueError('source interrupted')
    monkeypatch.setattr(SharadarSource, 'corroborate', fail)
    job = enqueue(conn)
    with pytest.raises(ValueError, match='source interrupted'):
        op.prepare(conn, job)
    status = jobs.status(conn, job)
    assert status['state'] == 'REFUSED'
    candidate = status['candidate_id']
    assert rolling_store.retired(conn, candidate)
    assert conn.execute('SELECT count(*) FROM sentinel_snapshot_bars').fetchone()[0] == 0
    assert conn.execute('SELECT count(*) FROM sentinel_snapshot_job_components WHERE job_id=%s', (job,)).fetchone()[0] > 0
    monkeypatch.setattr(SharadarSource, 'corroborate', original)
    result = publish(conn)
    assert len(list(rolling_store.read_bars(conn, result['candidate_id']))) == 600
    assert jobs.status(conn, job)['state'] == 'REFUSED'


def test_active_job_and_worker_scratch_survive_maintenance(conn, operational_source, monkeypatch):
    from sentinel.feed.rolling_source import SharadarSource
    import psycopg
    real = SharadarSource.corroborate
    def concurrent(source):
        # Candidate is sealed but worker retains its lease during corroboration.
        with psycopg.connect(conn.info.dsn) as other:
            assert MAINTAIN(other)['status'] == 'COMPLETE'
        assert conn.execute('SELECT count(*) FROM sentinel_snapshot_bars').fetchone()[0] == 600
        assert conn.execute('SELECT count(*) FROM sentinel_sep_staging').fetchone()[0] == 600
        return real(source)
    monkeypatch.setattr(SharadarSource, 'corroborate', concurrent)
    assert publish(conn)['data_version'] == 1


def test_explicit_read_only_generation_reader_pins_until_transaction_ends(conn, operational_source, monkeypatch):
    import psycopg
    monkeypatch.setattr(retention, 'maintain', lambda *_: None)
    first = publish(conn)
    publish(conn)
    conn.commit()
    with psycopg.connect(conn.info.dsn) as reader:
        reader.execute('SET TRANSACTION READ ONLY')
        assert len(list(rolling_store.read_bars(reader, first['candidate_id']))) == 600
        assert MAINTAIN(conn)['status'] == 'RETRY'
        reader.rollback()
    assert MAINTAIN(conn)['deleted_rows'] == 900


def test_history_outside_initial_basis_is_not_fabricated(conn, operational_source):
    publish(conn)
    with pytest.raises(feed_inputs.ExecutionInputsRefused, match='HISTORY_UNAVAILABLE'):
        feed_actions.action_lookup(conn, start=date(2000, 1, 3), end=date(2026, 9, 14))


def test_backup_authority_refusal_retains_data_and_retries(conn, operational_source, monkeypatch):
    from sentinel import backup_runtime_authority
    monkeypatch.setattr(retention, 'maintain', lambda *_: None)
    first = publish(conn)
    publish(conn)
    conn.commit()
    with monkeypatch.context() as patch:
        def refuse(*args, **kwargs):
            raise RuntimeError('backup authority unavailable')
        patch.setattr(backup_runtime_authority, 'require', refuse)
        assert MAINTAIN(conn)['status'] == 'RETRY'
        assert len(list(rolling_store.read_bars(conn, first['candidate_id']))) == 600
    conn.commit()
    assert MAINTAIN(conn)['deleted_rows'] == 900


def test_retained_payload_cannot_be_rehydrated_under_different_identity(conn, operational_source, monkeypatch):
    from sentinel.feed.rolling_source import SharadarSource
    def fail(*args):
        raise ValueError('source interrupted')
    monkeypatch.setattr(SharadarSource, 'corroborate', fail)
    with pytest.raises(ValueError, match='source interrupted'):
        publish(conn)
    sha = conn.execute('SELECT evidence_sha256 FROM sentinel_snapshot_evidence WHERE payload IS NULL LIMIT 1').fetchone()[0]
    conn.commit()
    with pytest.raises(Exception, match='retirement requires'):
        conn.execute("UPDATE sentinel_snapshot_evidence SET payload='{}'::jsonb,restored_bytes='{}' WHERE evidence_sha256=%s", (sha,))
    conn.rollback()


def test_pinned_candidates_do_not_starve_retirement(conn, operational_source, monkeypatch):
    import uuid
    monkeypatch.setattr(retention, 'maintain', lambda *_: None)
    first = publish(conn)
    publish(conn)
    template = conn.execute('SELECT window_start,window_end,session_axis,reference_sha256,source_evidence_sha256,dependencies_sha256 '
                            'FROM sentinel_price_candidates WHERE candidate_id=%s', (first['candidate_id'],)).fetchone()
    from sentinel.feed.rolling_contract import canonical_json
    for index in range(1, 34):
        conn.execute('INSERT INTO sentinel_price_candidates(candidate_id,window_start,window_end,session_axis,reference_sha256,source_evidence_sha256,dependencies_sha256) '
                     'VALUES(%s,%s,%s,%s::jsonb,%s,%s,%s)',
                     (str(uuid.UUID(int=index)), template[0], template[1], canonical_json(template[2]), *template[3:]))
    conn.commit()
    assert MAINTAIN(conn)['deleted_rows'] == 0
    assert MAINTAIN(conn)['deleted_rows'] == 900


def test_idempotent_schema_migration_after_cleanup_preserves_archive(conn, aged):
    expected = feed_actions.action_lookup(conn, start=date(2024, 12, 13), end=date(2026, 9, 14))('1')
    conn.commit()
    runtime_schema.migrate_feed_schema(conn)
    assert feed_actions.action_lookup(conn, start=date(2024, 12, 13), end=date(2026, 9, 14))('1') == expected


def test_advance_cannot_bridge_unobserved_action_interval(conn, operational_source, monkeypatch):
    aged_source(operational_source, monkeypatch, '2025-01-02')
    publish(conn)
    aged_source(operational_source, monkeypatch, '2026-09-14')
    with pytest.raises(ValueError, match='COVERAGE_GAP'):
        publish(conn)
    assert conn.execute('SELECT count(*) FROM sentinel_corpus_publications').fetchone()[0] == 1
    assert conn.execute('SELECT count(*) FROM sentinel_action_coverage').fetchone()[0] == 1


def test_retirement_requires_shared_writer_ownership(conn, operational_source, monkeypatch):
    monkeypatch.setattr(retention, 'maintain', lambda *_: None)
    first = publish(conn)
    publish(conn)
    conn.commit()
    with pytest.raises(Exception, match='retirement requires'):
        conn.execute('INSERT INTO sentinel_snapshot_retirements(candidate_id) VALUES(%s)', (first['candidate_id'],))
    conn.rollback()


def test_idle_maintenance_drains_backlog_without_another_publication(conn, operational_source, monkeypatch):
    monkeypatch.setattr(retention, 'maintain', lambda *_: None)
    for _ in range(4):
        latest = publish(conn)
    conn.commit()
    monkeypatch.setattr(retention, 'maintain', MAINTAIN)
    # One normal polling interval can perform independent bounded idle passes.
    for _ in range(10):
        if not retention.idle_pass(conn.info.dsn):
            break
    assert conn.execute('SELECT count(*) FROM sentinel_snapshot_bars').fetchone()[0] == 600
    assert not rolling_store.retired(conn, latest['candidate_id'])


def test_shadow_idle_loop_drains_then_yields_without_reacquisition(monkeypatch):
    from types import SimpleNamespace
    from sentinel import shadow_service as service
    handlers, clock, calls, advances = {}, [0], [], []
    monkeypatch.setattr(service.signal, 'signal', lambda sig, fn: handlers.setdefault(sig, fn))
    monkeypatch.setattr(service, 'service_health', lambda config: {})
    monkeypatch.setattr(service, 'advance_once', lambda config: advances.append(1) or {})
    monkeypatch.setattr(service.time, 'monotonic', lambda: clock[0])
    def sleep(seconds):
        clock[0] += seconds
        if clock[0] >= 3:
            handlers[service.signal.SIGTERM](None, None)
    monkeypatch.setattr(service.time, 'sleep', sleep)
    monkeypatch.setattr(retention, 'idle_pass', lambda url: calls.append(url) or len(calls) < 2)
    assert service.run(SimpleNamespace(database_url='unused', poll_seconds=300)) == 0
    assert calls == ['unused', 'unused'] and advances == [1]
