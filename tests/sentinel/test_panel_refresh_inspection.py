"""Operator inspection never upgrades expired or foreign evidence."""
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import inspect
import textwrap

import pytest

from sentinel.panel import authority_reader, model, render, sources

NOW = datetime(2026, 10, 11, 14, 28, tzinfo=timezone.utc)
OLD = 'base-20261011T131202Z'
NEW = 'base-20261011T141816Z'


def backup():
    return dict(base_at=NOW-timedelta(minutes=4), restore_at=NOW-timedelta(hours=1),
        runtime_at=NOW-timedelta(minutes=5), runtime_valid_until=NOW+timedelta(minutes=5), now=NOW,
        base_proof=dict(base_backup=NEW, marker='marker', marker_lsn='0/1', marker_wal='wal', system_identifier='123'),
        restore_proof=dict(base_backup=OLD, physical_only=False, marker='marker', target_lsn='0/1', system_identifier='123'),
        runtime_proof=dict(enabled=True, base_backup=OLD, system_identifier='123',
            wal_integrity='sha256-sidecar-v1', recoverable_from_wal='wal1', recoverable_through_wal='wal2', wal_segments=2),
        maintenance_at=NOW-timedelta(minutes=1), maintenance_proof=dict(
            schema='sentinel.backup-maintenance-progress/1', attempt='a'*32,
            started_at=int((NOW-timedelta(minutes=6)).timestamp()), deadline=int((NOW+timedelta(minutes=54)).timestamp()),
            system_identifier='123', image='sha256:'+'b'*64, predecessor_base=OLD, base_backup=NEW, phase='VERIFY_RESTORE'),
        expected_image='sha256:'+'b'*64)


def test_exact_backup_successor_waits_amber_then_requires_completed_chain():
    values = backup()
    row = model.backup_restore_row(**values)
    assert row.status == model.WARN and row.value == 'BACKUP CHECK IN PROGRESS'
    assert row.effective_status(NOW+timedelta(hours=1)) == model.FAIL
    values['runtime_proof']['base_backup'] = NEW
    values['runtime_at'] = NOW
    values['maintenance_proof']['phase'] = 'COMPLETE'
    assert model.backup_restore_row(**values).status == model.OK


@pytest.mark.parametrize('field,value', [('system_identifier','456'), ('base_backup',OLD),
    ('predecessor_base',NEW), ('phase','FAILED'), ('phase','COMPLETE'), ('phase','BASE_BACKUP'),
    ('deadline','unreadable'), ('deadline',int(NOW.timestamp())-1),
    ('deadline',int(NOW.timestamp())+3600), ('image','mutable:latest')])
def test_backup_progress_cannot_mask_a_real_mismatch(field, value):
    values = backup()
    values['maintenance_proof'][field] = value
    assert model.backup_restore_row(**values).status == model.FAIL


@pytest.mark.parametrize('which,field,value', [('runtime_proof','system_identifier','456'),
    ('runtime_proof','wal_integrity','bad'), ('restore_proof','physical_only',True),
    ('base_proof','marker',None)])
def test_other_backup_failures_remain_red_during_renewal(which, field, value):
    values = backup()
    values[which][field] = value
    assert model.backup_restore_row(**values).status == model.FAIL


def test_backup_transition_identity_guard_has_a_falsifier():
    code = textwrap.dedent(inspect.getsource(model.backup_restore_row))
    mutated = code.replace('identity_matches and start <= now < end', 'start <= now < end')
    assert code != mutated
    namespace = dict(vars(model))
    exec(mutated, namespace)
    values = backup()
    values['maintenance_proof']['base_backup'] = OLD
    assert model.backup_restore_row(**values).status == model.FAIL
    assert namespace['backup_restore_row'](**values).status == model.WARN


@pytest.mark.parametrize('field,value', [('base_at',NOW-timedelta(hours=27)),
    ('base_at',NOW+timedelta(seconds=1)), ('restore_at',NOW+timedelta(seconds=1)),
    ('expected_image','sha256:'+'c'*64), ('expected_image',None)])
def test_renewal_cannot_mask_expired_future_or_foreign_image_evidence(field, value):
    values = backup()
    values[field] = value
    assert model.backup_restore_row(**values).status == model.FAIL


def canonical_state():
    return dict(wealth_core=dict(cash='50', episodes={'1':dict(security_id='sid', ticker='A<B', current_shares='2')}),
                feed=dict(series={'sid':dict(sessions=['2026-10-09'], raw_closes=['25'])}), pending=[])


def test_holdings_come_from_canonical_state_with_exact_arithmetic_and_escaped_copy():
    state = canonical_state()
    original = deepcopy(state)
    book = sources._shadow_holdings(state, '2026-10-09', Decimal('100'))
    assert state == original
    assert book.holdings[0].value == Decimal('50') and book.holdings[0].weight == Decimal('.5')
    raw = dict(key='book', label='Book', value='summary', status=model.OK, detail='', shadow_book=book.model_dump(mode='json'))
    row = authority_reader._row_from_observation(raw)
    html = render._row_html(row, NOW)
    assert 'View shadow holdings' in html and 'A&lt;B' in html and '$50.00' in html
    assert 'controller' in html and 'transaction costs' in html
    assert 'View shadow holdings' not in render._row_html(replace(row, status=model.UNKNOWN), NOW)
    expired = replace(row, as_of=NOW-timedelta(minutes=11), freshness=timedelta(minutes=10), required_current=True)
    assert 'View shadow holdings' not in render._row_html(expired, NOW)


def test_missing_exact_session_marks_are_unavailable_and_pending_is_not_filled():
    state = canonical_state()
    state['feed']['series']['sid']['sessions'] = ['2026-10-08']
    state['pending'] = [dict(operation='OPEN_SLOT_POSITION', security_id='other', shares='9')]
    book = sources._shadow_holdings(state, '2026-10-09', Decimal('100'))
    assert book.pending_operations == 1 and len(book.holdings) == 1
    assert book.holdings[0].raw_close is None and book.holdings[0].value is None


@pytest.mark.parametrize('field,value', [('quantity','NaN'), ('quantity','-1'), ('value','99'), ('weight','1')])
def test_observer_refuses_malformed_holdings(field, value):
    book = sources._shadow_holdings(canonical_state(), '2026-10-09', Decimal('100')).model_dump(mode='json')
    book['holdings'][0][field] = value
    with pytest.raises(ValueError):
        authority_reader._row_from_observation(dict(key='book', label='Book', value='summary', shadow_book=book))


def test_operational_acquisition_reads_current_jobs_without_legacy_fallback():
    class Connection:
        def execute(self, query):
            assert 'sentinel_operational_snapshot_jobs' in query and 'feed_ingest_runs' not in query
            return self
        def fetchone(self):
            return ('PUBLISHED', 'PUBLISHED', NOW, 345, 7)
    result = sources._operational_acquisition(Connection())[0]
    assert result['status'] == 'success' and 'publication 7' in result['current_chunk']
    assert result['rows_written'] == 345


def test_terminal_cycle_failure_is_not_a_claim_about_broker_positions(monkeypatch):
    monkeypatch.setattr(sources, '_informational_mirror_count', lambda c: 0)
    monkeypatch.setattr(sources, '_latest_automation_cycle', lambda c: dict(state='BLOCKED',
        decision_session='2026-10-09', failure_code='CorpusLockUnavailable', failure_detail='publication lock'))
    row = sources._dual_paper_row(None, informational_paper_mirror=None, publication=None, feed_store=None)
    assert row.status == model.FAIL and 'LATEST CYCLE FAILED' in row.value
    assert 'MISMATCH' not in row.value and '2026-10-09' in row.detail
    assert 'publication lock' in row.detail
