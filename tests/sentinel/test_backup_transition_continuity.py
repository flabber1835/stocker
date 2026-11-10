"""One admitted maintenance row survives the ordinary chain-clock transition."""
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
import inspect
import textwrap

import pytest

from sentinel.panel import model, presentation, review
from tests.sentinel.test_backup_renewal_projection import copying, stamp
from tests.sentinel.test_dashboard_review import conn, pg  # noqa: F401
from tests.sentinel.test_panel_historical_mirror_schedule import healthy_history_panel


def before_expiry():
    values = copying()
    values['now'] = values['runtime_valid_until'] - timedelta(seconds=1)
    return values


def assert_frozen_continuity(builder):
    values = before_expiry()
    original = deepcopy(values)
    row = builder(**values)
    assert row.status == model.WARN and row.value == 'BACKUP CHECK IN PROGRESS'
    assert row.as_of == values['maintenance_at']
    assert row.recovery.phase == 'BACKUP_MAINTENANCE'
    assert row.valid_until == row.recovery.deadline == stamp('10:04:53')
    for now in (values['now'], values['runtime_valid_until'],
                values['runtime_valid_until'] + timedelta(microseconds=1),
                values['runtime_valid_until'] + timedelta(seconds=16)):
        # Advance only the consumer's time; never rebuild the admitted row.
        page = model.Panel(rows=[row], now=now)
        assert row.effective_status(now) == model.WARN
        assert presentation.health_facts(page) == {'active': [], 'warnings': []}
        assert presentation._normal_warning(page, row)
        fresh = builder(**{**values, 'now': now})
        assert (fresh.status, fresh.as_of, fresh.valid_until, fresh.recovery) == (
            row.status, row.as_of, row.valid_until, row.recovery)
        assert presentation.health_facts(model.Panel(rows=[fresh], now=now)) == {
            'active': [], 'warnings': []}
    assert values == original
    return row


def test_preexpiry_copying_fact_keeps_its_own_original_deadline_without_recollection():
    row = assert_frozen_continuity(model.backup_restore_row)
    assert row.effective_status(row.valid_until + timedelta(microseconds=1)) == model.FAIL
    expired = model.Panel(rows=[row], now=row.valid_until + timedelta(microseconds=1))
    assert presentation.health_facts(expired) == {'active': ['backup_restore'], 'warnings': []}


def test_restoring_expired_only_admission_fails_the_frozen_row_oracle():
    code = textwrap.dedent(inspect.getsource(model.backup_restore_row))
    guard = 'and not hard_failures and (not lag_failures or ordinary_lag)'
    assert code.count(guard) == 1
    namespace = dict(vars(model))
    exec(compile(code.replace(guard, 'and ordinary_lag'), '<old-expired-only-admission>', 'exec'), namespace)
    with pytest.raises(AssertionError):
        assert_frozen_continuity(namespace['backup_restore_row'])


@pytest.mark.parametrize('kind', ['base', 'drill'])
def test_preexpiry_maintenance_never_outlives_an_earlier_independent_objective(kind):
    values = before_expiry()
    boundary = values['now'] + timedelta(seconds=20)
    values['base_at' if kind == 'base' else 'restore_at'] = boundary - (
        timedelta(hours=26) if kind == 'base' else timedelta(days=31))
    # The maintenance observation must still follow the verified base.
    row = model.backup_restore_row(**values)
    assert row.status == model.WARN
    assert row.valid_until == row.recovery.deadline == boundary
    assert row.effective_status(boundary + timedelta(microseconds=1)) == model.FAIL


@pytest.mark.parametrize('fault', ['missing', 'future', 'image', 'cluster', 'lineage',
    'predecessor', 'old_chain', 'old_base', 'old_drill', 'integrity', 'marker',
    'failed', 'complete', 'expired_attempt', 'unbounded_attempt'])
def test_preexpiry_invalid_progress_cannot_be_admitted_or_survive_chain_expiry(fault):
    values = before_expiry()
    if fault == 'missing': values['maintenance_proof'] = None
    elif fault == 'future': values['maintenance_at'] = values['now'] + timedelta(seconds=1)
    elif fault == 'image': values['maintenance_proof']['image'] = 'mutable:latest'
    elif fault == 'cluster': values['maintenance_proof']['system_identifier'] = '456'
    elif fault == 'lineage': values['maintenance_proof']['base_backup'] = 'base-20261109T090457Z'
    elif fault == 'predecessor': values['maintenance_proof']['predecessor_base'] = 'base-20261107T090000Z'
    elif fault == 'old_chain': values['runtime_at'] = stamp('08:50:00')
    elif fault == 'old_base': values['base_at'] = values['now'] - timedelta(hours=27)
    elif fault == 'old_drill': values['restore_at'] = values['now'] - timedelta(days=32)
    elif fault == 'integrity': values['runtime_proof']['wal_integrity'] = 'bad'
    elif fault == 'marker': values['base_proof'].pop('marker')
    elif fault == 'expired_attempt': values['maintenance_proof']['deadline'] = int(values['now'].timestamp())
    elif fault == 'unbounded_attempt': values['maintenance_proof']['deadline'] += 1
    else: values['maintenance_proof']['phase'] = fault.upper()
    row = model.backup_restore_row(**values)
    assert row.recovery is None
    assert row.value != 'BACKUP CHECK IN PROGRESS'
    after = values['runtime_valid_until'] + timedelta(microseconds=1)
    assert row.effective_status(after) == model.FAIL
    assert presentation.health_facts(model.Panel(rows=[row], now=after)) == {
        'active': ['backup_restore'], 'warnings': []}


@pytest.mark.parametrize('phase', ['VERIFY_CHAIN', 'VERIFY_RESTORE'])
def test_preexpiry_admission_does_not_expand_successor_verification_policy(phase):
    values = before_expiry()
    values['maintenance_proof']['phase'] = phase
    row = model.backup_restore_row(**values)
    assert row.status == model.OK and row.recovery is None
    assert row.valid_until == values['runtime_valid_until']


def test_frozen_maintenance_preserves_independent_hard_failure():
    row = assert_frozen_continuity(model.backup_restore_row)
    page = model.Panel(rows=[row, model.Row('broker', 'Broker', 'DOWN', model.FAIL)],
        now=stamp('09:09:51'))
    assert presentation.health_facts(page) == {'active': ['broker'], 'warnings': []}


def test_signed_review_has_no_failure_or_review_event_across_the_old_chain_deadline(conn):
    owner = review.Recorder()
    page = healthy_history_panel()
    initial = owner.observe(page, conn.info.dsn)
    baseline = owner.acknowledge(page, conn.info.dsn, initial.token, actor='private qualification operator')
    values = before_expiry()
    offset = page.now - values['now']
    for key in ('now', 'base_at', 'restore_at', 'runtime_at', 'runtime_valid_until', 'maintenance_at'):
        values[key] += offset
    for key in ('started_at', 'deadline'):
        values['maintenance_proof'][key] += int(offset.total_seconds())
    row = model.backup_restore_row(**values)
    original = deepcopy(row)
    waiting = replace(page, rows=[row if value.key == row.key else value for value in page.rows])
    for at in (page.now, values['runtime_valid_until'], values['runtime_valid_until'] + timedelta(seconds=2)):
        sampled = replace(waiting, now=at)
        assert presentation.health_facts(sampled) == {'active': [], 'warnings': []}
        current = owner.observe(sampled, conn.info.dsn)
        assert current.status == 'CLEAN' and current.head == current.reviewed_head == baseline.head
        assert [event for event in current.events if event['sequence'] > baseline.head] == []
    assert row == original
    restored = owner.observe(replace(page, now=sampled.now), conn.info.dsn)
    assert restored.status == 'CLEAN' and restored.head == baseline.head
