from datetime import datetime, timedelta, timezone

import pytest

from sentinel.operational_status import RecoveryEvidence
from sentinel.panel import model
from sentinel.panel.presentation import describe
from sentinel.panel.render import _row_html


NOW = datetime(2026, 10, 22, 22, tzinfo=timezone.utc)


def test_strategy_value_unscaled_book_and_broker_account_are_distinct_views():
    nav = describe(model.Row('shadow_nav', 'NAV', '$50,000', model.OK), model.OK)
    book = describe(model.Row('book', 'Book', '12/20 slots', model.OK), model.OK)
    account = describe(model.Row('actual_account', 'Account', '$49,000', model.OK), model.OK)
    assert nav[0] == 'Simulated strategy value'
    assert 'Core allocation and Treasury-bill sleeve' in nav[2] and 'including costs' in nav[2]
    assert 'unscaled Wealth Core book' in nav[2] and 'Alpaca PAPER account' in nav[2]
    assert book[0] == 'Unscaled Wealth Core book'
    assert 'Book weights use this book’s own total value' in book[2]
    assert 'Receivables are not spending cash' in book[2]
    assert 'simulated money held at Alpaca' in account[2]


@pytest.mark.parametrize('raw,shown', [
    ('1.00', '100%'), ('0.65', '65%'), ('0.00', '0%'),
    ('0.555', '55.5%'), ('1.00 PINNED', '100% · PINNED'),
    ('0.65 NOT ADOPTED', '65% · NOT ADOPTED'),
])
def test_core_fraction_formats_as_percent_without_losing_plan_caveats(raw, shown):
    row = model.Row('exposure', 'Exposure', raw, model.OK, 'decision evidence')
    label, value, explanation = describe(row, model.OK)
    assert label == 'Planned Core exposure' and value == shown
    assert 'Core can retain cash' in explanation and 'not measured stock exposure' in explanation
    html = _row_html(row, NOW)
    assert f'Exposure · {raw}<br>decision evidence' in html
    assert row.value == raw and row.status == model.OK


@pytest.mark.parametrize('raw', [
    'UNKNOWN', 'NaN', 'Infinity', '-0.1', '1.01', '0.65 UNVERIFIED',
    '1E-999999', '0E+999999', 'not a number', '0.65 ', '0.6_5', '+0.65',
])
def test_unavailable_or_invalid_exposure_is_not_fabricated_as_a_percentage(raw):
    row = model.Row('exposure', 'Exposure', raw, model.UNKNOWN, 'unreadable evidence')
    _, value, explanation = describe(row, model.UNKNOWN)
    assert value == ('Status unavailable' if raw == 'UNKNOWN' else raw)
    assert 'Attention needed' in explanation
    assert 'data-status="unknown"' in _row_html(row, NOW)
    assert row.value == raw and row.status == model.UNKNOWN


def test_scheduled_paper_green_is_only_readiness_to_wait_and_expiry_stays_failed():
    start = NOW+timedelta(hours=15)
    row = model.paper_reconciliation_row(state='SCHEDULED', scheduled_until=start,
                                        detail='original scheduled proof')
    label, value, explanation = describe(row, model.OK)
    assert label == 'Paper alignment pending'
    assert 'alignment and post-close verification pending' in value
    assert 'ready to wait' in explanation and 'not proof of submitted orders' in explanation
    assert 'verified PAPER performance' in explanation
    html = _row_html(row, NOW)
    assert 'data-status="ok"' in html
    assert 'PAPER NOT VERIFIED · SCHEDULED · POST-CLOSE EVIDENCE PENDING' in html
    expired = _row_html(row, start+timedelta(seconds=1))
    assert 'data-status="fail"' in expired
    assert 'Scheduled readiness cannot be confirmed' in expired
    assert 'Attention needed' in expired


def test_local_backup_and_runtime_copy_do_not_claim_restore_or_release_verification():
    backup = model.Row('backup_restore', 'Backup and restore', 'DISABLED BY OWNER',
                       model.OK, 'backup creation, drills and verification are suspended')
    runtime = model.Row('runtime_identity', 'Runtime identity', 'LOCAL PAPER 0123456789ab',
                        model.OK, 'Owner-authorized local branch; image sha256:original')
    label, _, explanation = describe(backup, model.OK)
    assert label == 'Backups suspended'
    assert 'Backup creation, restore drills and backup verification are suspended' in explanation
    assert 'No restore assurance is claimed' in explanation
    assert 'recent database backup can actually be restored' not in explanation
    label, _, explanation = describe(runtime, model.OK)
    assert label == 'Installed local software'
    assert 'PR release certification is suspended' in explanation
    assert 'authority certificate’s original software references' in explanation
    assert 'matches the reviewed release' not in explanation
    assert 'image sha256:original' in _row_html(runtime, NOW)
    normal_backup = model.Row('backup_restore', 'Backup', 'BASE 1h · RESTORE 2d', model.OK)
    normal_runtime = model.Row('runtime_identity', 'Runtime', 'GIT original · IMAGE original', model.OK)
    assert 'recent database backup can actually be restored' in describe(normal_backup, model.OK)[2]
    assert 'matches the reviewed release' in describe(normal_runtime, model.OK)[2]


@pytest.mark.parametrize('key,phase', [
    ('automation_cycle', 'AUTOMATION_WAITING_OPEN'),
    ('automation_step_open', 'AUTOMATION_OPEN'),
])
def test_wait_uses_typed_pacific_start_and_distinguishes_market_close_deadline(key, phase):
    start = datetime(2026, 10, 23, 13, 31, tzinfo=timezone.utc)
    deadline = datetime(2026, 10, 23, 20, tzinfo=timezone.utc)
    row = model.Row(key, 'Original wait', 'WAITING_OPEN', model.WARN,
        'unparsed schedule 2040-01-01 13:40Z', NOW, required_current=True,
        recovery=RecoveryEvidence(phase=phase, automatic=True,
            next_attempt_at=start, deadline=deadline))
    label, value, explanation = describe(row, model.WARN)
    assert label == ('Current daily run' if key == 'automation_cycle' else 'Wait for market open')
    assert value == 'Waiting for market open'
    assert 'Saved execution start: 2026-10-23 at 06:31 AM Pacific' in explanation
    assert 'Saved recovery deadline (market close): 2026-10-23 at 01:00 PM Pacific' in explanation
    assert 'separate from the execution start and the new-order submission cutoff' in explanation
    assert '2040-01-01' not in explanation and '13:40' not in explanation
    assert row.recovery.next_attempt_at == start and row.recovery.deadline == deadline
    assert 'unparsed schedule 2040-01-01 13:40Z' in _row_html(row, NOW)


@pytest.mark.parametrize('phase,start', [
    ('UNRELATED_PHASE', datetime(2026, 10, 23, 13, 31, tzinfo=timezone.utc)),
    ('AUTOMATION_OPEN', datetime(2026, 10, 23, 13, 31)),
])
def test_schedule_copy_does_not_interpret_other_recoveries_or_naive_times(phase, start):
    row = model.Row('automation_step_open', 'Wait', 'WAITING_OPEN', model.WARN,
        'scheduled 2040-01-01 13:40Z', recovery=RecoveryEvidence(
            phase=phase, automatic=True, next_attempt_at=start))
    explanation = describe(row, model.WARN)[2]
    assert 'Saved execution start:' not in explanation and '2040-01-01' not in explanation


def test_future_steps_are_pending_predecessors_while_disabled_steps_are_not_running():
    row = model.Row('automation_step_reconcile', '6 · Broker reconciliation',
                    'NOT REACHED', model.PENDING, 'waiting on transport')
    _, value, explanation = describe(row, model.PENDING)
    assert value == 'Pending earlier steps'
    assert 'pending until its predecessor completes' in explanation
    assert 'no completion is claimed' in explanation
    html = _row_html(row, NOW)
    assert 'data-status="pending"' in html
    assert 'NOT REACHED<br>waiting on transport' in html
    maintenance = model.Row('automation_step_reconcile', 'Reconcile', 'MAINTENANCE', model.PENDING)
    assert 'deliberately disabled; this step is not running' in describe(maintenance, model.PENDING)[2]
    assert describe(model.Row('automation_cycle', 'Cycle', 'COMPLETE', model.OK), model.OK)[0] == 'Current daily run'
    assert describe(model.Row('automation_step_prepare', 'Prepare', 'COMPLETE', model.OK), model.OK)[0] == 'Calculate the next trading plan'


def test_notification_counts_and_sender_copy_separate_delivery_from_acknowledgement():
    row = model.Row('automation_alerts', 'Automation alerts', '2 pending · 1 DLQ · 3 unacked',
                    model.FAIL, 'original alert evidence')
    _, value, explanation = describe(row, model.FAIL)
    assert value == '2 awaiting delivery · 1 failed delivery · 3 unacknowledged alerts'
    assert 'Acknowledgement and delivery are separate' in explanation
    html = _row_html(row, NOW)
    assert 'data-status="fail"' in html
    assert '2 pending · 1 DLQ · 3 unacked<br>original alert evidence' in html
    sender = describe(model.Row('alert_dispatcher', 'Alert delivery', '1 healthy', model.OK), model.OK)
    assert 'sender health and recorded delivery attempts' in sender[2]
    assert 'does not confirm receipt on your device' in sender[2]
    unknown = model.Row('automation_alerts', 'Alerts', 'UNKNOWN', model.UNKNOWN, 'missing counts')
    assert describe(unknown, model.UNKNOWN)[1] == 'Status unavailable'
    assert 'data-status="unknown"' in _row_html(unknown, NOW)
