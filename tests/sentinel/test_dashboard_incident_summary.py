"""Incident summaries preserve exact signed records and explain their limits."""

from datetime import datetime, timedelta, timezone
from hashlib import sha256

import pytest

from sentinel.panel.review_history import condition_label, summarize


NOW = datetime(2026, 11, 22, 10, 13, 40, tzinfo=timezone.utc)
DISPATCHER = 'alert_dispatcher'
SCHEDULE = ['automation_cycle', 'automation_step_open', 'paper_reconciliation']


def event(sequence, kind, *, seen=0, conditions=(), previous=(), evidence=None, **details):
    return dict(sequence=sequence, kind=kind, at=(NOW + timedelta(seconds=seen)).isoformat(),
                details=dict(conditions=list(conditions), previous=list(previous),
                             evidence=evidence or {}, **details))


def fact(seen, value, phase, *, status='warn', raw=None, scheduled=False):
    as_of = datetime(2026, 11, 21, 23, 58, tzinfo=timezone.utc) if scheduled else NOW
    end = None
    if scheduled:
        end = ('2026-11-23T14:30:59.999999+00:00' if phase is None
               else '2026-11-23T21:00:00+00:00')
    return dict(code='ROW_CONDITION', raw_status=raw or status, effective_status=status,
                sampled_at=(NOW + timedelta(seconds=seen, milliseconds=-5)).isoformat(),
                as_of=(as_of + timedelta(seconds=seen, milliseconds=-10)).isoformat()
                if not scheduled else as_of.isoformat(),
                original_valid_until=end, recovery_phase=phase,
                value_sha256=sha256(value.encode()).hexdigest())


def dispatcher(seen, status):
    phase = 'ALERT_TRANSPORT' if status == 'warn' else None
    return {DISPATCHER: fact(seen, 'notification delivery', phase, status=status)}


def schedule(seen):
    return {
        SCHEDULE[0]: fact(seen, 'WAITING_OPEN', 'AUTOMATION_WAITING_OPEN', scheduled=True),
        SCHEDULE[1]: fact(seen, 'WAITING_OPEN', 'AUTOMATION_OPEN', scheduled=True),
        SCHEDULE[2]: fact(seen, 'PAPER NOT VERIFIED · SCHEDULED · HISTORICAL MIRROR WARNING',
                          None, scheduled=True),
    }


def test_legacy_notification_episodes_keep_each_original_record():
    both = [DISPATCHER, *SCHEDULE]
    records = [
        event(1, 'REVIEW', conditions=both, evidence={**dispatcher(0, 'warn'), **schedule(0)}),
        event(2, 'FAILED', seen=47, conditions=[DISPATCHER], evidence=dispatcher(47, 'fail')),
        event(3, 'REVIEW', seen=47, conditions=SCHEDULE, previous=both,
              evidence={**dispatcher(47, 'fail'), **schedule(47)}),
        event(4, 'RECOVERED', seen=76, previous=[DISPATCHER], evidence=dispatcher(76, 'ok')),
        event(5, 'RECOVERED', seen=76, previous=SCHEDULE, evidence=schedule(76)),
        event(6, 'FAILED', seen=1000, conditions=[DISPATCHER], evidence=dispatcher(1000, 'fail')),
        event(7, 'REVIEW', seen=1000, conditions=SCHEDULE, evidence=schedule(1000)),
        event(8, 'RECOVERED', seen=1006, previous=[DISPATCHER], evidence=dispatcher(1006, 'warn')),
        event(9, 'REVIEW', seen=1006, conditions=both, previous=SCHEDULE,
              evidence={**dispatcher(1006, 'warn'), **schedule(1006)}),
        event(10, 'FAILED', seen=1020, conditions=[DISPATCHER], evidence=dispatcher(1020, 'fail')),
        event(11, 'REVIEW', seen=1020, conditions=SCHEDULE, previous=both,
              evidence={**dispatcher(1020, 'fail'), **schedule(1020)}),
        event(12, 'RECOVERED', seen=1080, previous=[DISPATCHER], evidence=dispatcher(1080, 'ok')),
        event(13, 'RECOVERED', seen=1080, previous=SCHEDULE, evidence=schedule(1080)),
    ]

    newest, earliest = summarize(list(reversed(records)))

    assert (newest.key, earliest.key) == (DISPATCHER, DISPATCHER)
    assert newest.kind == earliest.kind == 'INCIDENT'
    assert newest.started_at == records[5]['at'] and newest.recovered_at == records[11]['at']
    assert earliest.started_at == records[0]['at'] and earliest.recovered_at == records[3]['at']
    assert newest.records == tuple(reversed(records[5:]))
    assert earliest.records == tuple(reversed(records[:5]))


def test_retry_is_not_recovery_and_short_page_does_not_invent_a_start():
    retry = event(12, 'RECOVERED', previous=[DISPATCHER], evidence=dispatcher(0, 'warn'))
    failed = event(13, 'FAILED', seen=10, conditions=[DISPATCHER], evidence=dispatcher(10, 'fail'))
    active, = summarize([failed, retry])
    assert active.started_at is None and active.recovered_at is None
    assert active.records == (failed, retry)

    recovered = event(14, 'RECOVERED', seen=20, previous=[DISPATCHER], evidence=dispatcher(20, 'ok'))
    older_page, = summarize([recovered])
    assert older_page.started_at is None
    assert older_page.recovered_at == recovered['at']


@pytest.mark.parametrize('changed', ['other_sample', 'mirror_digest', 'different_deadline', 'failed_cycle'])
def test_uncertain_legacy_schedule_stays_visible(changed):
    facts = schedule(5)
    if changed == 'other_sample':
        pair = dispatcher(4, 'fail')
    else:
        pair = dispatcher(5, 'fail')
    if changed == 'mirror_digest':
        facts[SCHEDULE[2]]['value_sha256'] = 'a' * 64
    if changed == 'different_deadline':
        facts[SCHEDULE[1]]['original_valid_until'] = '2026-11-23T21:01:00+00:00'
    if changed == 'failed_cycle':
        facts[SCHEDULE[0]]['effective_status'] = 'fail'
    started = event(1, 'FAILED', seen=5, conditions=[DISPATCHER], evidence=pair)
    waiting = event(2, 'REVIEW', seen=5, conditions=SCHEDULE, evidence=facts)
    assert {entry.key for entry in summarize([waiting, started])} == {DISPATCHER, *SCHEDULE}


def test_concurrent_component_and_signed_level_changes_have_independent_lifetimes():
    failed = event(1, 'FAILED', conditions=[DISPATCHER], evidence=dispatcher(0, 'fail'))
    backup = event(2, 'REVIEW', seen=4, conditions=['backup_restore'])
    waiting = event(3, 'REVIEW', seen=6, conditions=[DISPATCHER], previous=['backup_restore'],
                    evidence=dispatcher(6, 'warn'))
    done = event(4, 'RECOVERED', seen=14, previous=[DISPATCHER],
                 evidence=dispatcher(14, 'warn'), transition='RESOLVED')
    dispatcher_entry, backup_entry = summarize([done, waiting, backup, failed])
    assert dispatcher_entry.records == (done, waiting, failed)
    assert dispatcher_entry.recovered_at == done['at']
    assert backup_entry.records == (backup,)
    assert backup_entry.recovered_at is None
    assert backup_entry.started_at == backup['at']


def test_standalone_legacy_notices_and_unrecognized_conditions_keep_their_text():
    notation = event(1, 'REVIEW', conditions=['shadow_verification'],
                     component='verifier', reason='Verification attempt failed')
    unknown = event(2, 'FAILED', seen=4, conditions=['<legacy vendor>'])
    legacy, note = summarize([unknown, notation])
    assert legacy.key == '<legacy vendor>' and legacy.records == (unknown,)
    assert note.kind == 'REVIEW' and note.records == (notation,)
    assert condition_label(legacy.key) == '<legacy vendor>'
    assert condition_label(DISPATCHER) == 'Notification delivery'
    assert condition_label('missing:automation_step_open') == 'Missing check · Wait for scheduled execution'
