"""Independent broker observation clocks and UTC producer/wire handoffs."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import inspect
import textwrap

import pytest

from sentinel import local_paper
from sentinel.feed import calendar, store
from sentinel.panel import model, observer_failure, operational_snapshot as snapshots, sources
from sentinel.panel import postclose_feed_wait as waiting
from tests.sentinel.test_operator_monitoring import db, issue369_pg  # noqa: F401

NOW = datetime(2026, 11, 9, 21, 49, 35, tzinfo=timezone.utc)
CONTEXT = 'a' * 64
SUBJECTS = {'SHADOW': 'b' * 64, 'PAPER': 'c' * 64}


@pytest.fixture(autouse=True)
def signing_key(monkeypatch):
    monkeypatch.setenv('SENTINEL_PUBLICATION_RECEIPT_KEY', 'private-close-clocks-' + 'x' * 40)


def records(db, monkeypatch, *, cycle, age=timedelta(seconds=17), power='40', flags='{}'):
    """Use actual durable account/observation readers, with unrelated guards isolated."""
    observed = NOW - age
    db.execute("INSERT INTO sentinel_broker_account_evidence "
        "(broker,broker_account_id,status,flags,equity,cash,buying_power,multiplier,observed_at) "
        "VALUES ('alpaca','paper-clock','ACTIVE',%s::jsonb,100,40,%s,1,%s)",
        (flags, power, observed))
    db.execute("INSERT INTO sentinel_observations(observed_at,completeness,runtime_state) "
        "VALUES (%s,'COMPLETE','RUNNING')", (observed,))
    db.commit()
    monkeypatch.setattr(sources, '_latest_automation_cycle', lambda *a, **kw: cycle)
    monkeypatch.setattr(sources, '_bound_account_id', lambda _c: 'paper-clock')
    monkeypatch.setattr(sources, '_matched_resting_reservation', lambda *a, **kw: None)
    monkeypatch.setattr(local_paper, 'require_bound_account', lambda _c: False)
    monkeypatch.setattr(local_paper, 'backups_suspended_for_account', lambda _c: True)
    monkeypatch.setenv('SENTINEL_REVIEWED_DEPLOYMENT_MODE', 'shadow')
    return observed


def read_facts(db):
    account_rows, _ = sources._operator_evidence_rows(db.info.dsn, now=NOW)
    runtime_rows, _ = sources._runtime_projection(db.info.dsn, include_book=False, now=NOW)
    return (next(r for r in account_rows if r.key == 'alpaca_account'),
            next(r for r in runtime_rows if r.key == 'broker'))


@pytest.mark.parametrize('cycle', [
    {'state': 'RETRY_WAIT', 'retry_phase': 'REFRESH', 'next_wake_at': NOW-timedelta(seconds=1)},
    {'state': 'RETRY_WAIT', 'retry_phase': 'PREPARE', 'next_wake_at': NOW+timedelta(hours=4)},
    {'state': 'REFRESHING_DATA', 'next_wake_at': None, 'decision_session': '2026-11-09'},
    {'state': 'WAITING_OPEN', 'next_wake_at': NOW+timedelta(hours=17)},
])
def test_fresh_account_and_broker_do_not_borrow_trading_wake(db, monkeypatch, cycle):
    observed = records(db, monkeypatch, cycle=cycle)
    for row in read_facts(db):
        assert row.effective_status(NOW) == model.OK, row.detail
        assert row.as_of == observed
        assert row.valid_until == observed+timedelta(minutes=10)
        assert row.effective_status(row.valid_until+timedelta(microseconds=1)) == model.FAIL


def test_future_wake_cannot_keep_stopped_broker_producers_current(db, monkeypatch):
    records(db, monkeypatch, age=timedelta(minutes=11),
        cycle={'state': 'WAITING_OPEN', 'next_wake_at': NOW+timedelta(hours=17)})
    assert all(row.effective_status(NOW) == model.FAIL for row in read_facts(db))


def test_phase_change_cannot_renew_same_recorded_observation(db, monkeypatch):
    cycle = {'state': 'RETRY_WAIT', 'retry_phase': 'REFRESH',
             'next_wake_at': NOW-timedelta(seconds=1)}
    records(db, monkeypatch, cycle=cycle)
    before = read_facts(db)
    cycle.update(state='REFRESHING_DATA', next_wake_at=None, decision_session='2026-11-09')
    after = read_facts(db)
    assert [(r.as_of, r.valid_until) for r in before] == [(r.as_of, r.valid_until) for r in after]


def test_account_blocking_negative_is_not_changed_by_independent_clock(db, monkeypatch):
    records(db, monkeypatch, flags='{"trading_blocked":true}',
        cycle={'state': 'REFRESHING_DATA', 'next_wake_at': None})
    assert read_facts(db)[0].effective_status(NOW) == model.FAIL


def test_operator_reservation_keeps_its_stricter_original_expiry(db, monkeypatch):
    from sentinel.execution import account_status
    observed = records(db, monkeypatch, power='38',
        cycle={'state': 'REFRESHING_DATA', 'next_wake_at': None})
    expiry = NOW+timedelta(seconds=30)
    monkeypatch.setattr(local_paper, 'require_bound_account', lambda _c: True)
    monkeypatch.setattr(local_paper, 'require_runtime', lambda *a, **kw: None)
    monkeypatch.setenv('SENTINEL_GIT_COMMIT', 'a'*40)
    monkeypatch.setenv('SENTINEL_RUNTIME_IMAGE_DIGEST', 'sha256:'+'b'*64)
    monkeypatch.setattr(account_status, 'recorded_reservation', lambda *a, **kw:
        {'reserved_cash': '2', 'valid_until': expiry.isoformat()})
    account = read_facts(db)[0]
    assert account.as_of == observed and account.effective_status(NOW) == model.OK
    assert account.valid_until == expiry
    assert account.effective_status(expiry+timedelta(microseconds=1)) == model.FAIL


def test_real_database_offset_timestamps_enter_signed_rows_in_utc(db, monkeypatch):
    observed = records(db, monkeypatch,
        cycle={'state': 'WAITING_OPEN', 'next_wake_at': NOW+timedelta(hours=17)})
    connect = store.connect
    def exchange_connection(*args, **kwargs):
        conn = connect(*args, **kwargs)
        conn.execute("SET TIME ZONE 'America/New_York'")
        return conn
    monkeypatch.setattr(store, 'connect', exchange_connection)
    rows = list(read_facts(db))
    assert all(r.as_of == observed and r.as_of.utcoffset() == timedelta(0) for r in rows)
    value, signed = snapshots.encode(model.Panel(rows=rows, now=NOW),
        context_sha256=CONTEXT, subjects=SUBJECTS)
    restored = snapshots.decode(value, signed, context_sha256=CONTEXT, now=NOW)
    assert all(r.as_of == observed for r in restored.panel.rows)


@pytest.mark.parametrize('value', [NOW.replace(tzinfo=None), '2026-11-09T21:49:35',
                                  'not-a-clock', 123, object()])
def test_unidentified_clock_never_gains_a_guessed_timezone(value):
    with pytest.raises(ValueError, match='source clock'):
        sources._utc(value)


def test_known_aware_instants_and_absence_have_distinct_source_meanings():
    local = NOW.astimezone(timezone(timedelta(hours=-5)))
    assert sources._utc(local) == NOW
    assert sources._utc(local.isoformat()).utcoffset() == timedelta(0)
    assert sources._utc(None) is None


def protected_account():
    from tests.sentinel.test_operator_monitoring import day_wait_wait_payload
    observed = datetime(2026, 10, 20, 20, 9, tzinfo=timezone.utc)
    proof = day_wait_wait_payload(now=observed)
    row = model.alpaca_account_row(available=True, broker='alpaca',
        account_id='synthetic-account', expected_account_id='synthetic-account', status='ACTIVE',
        flags={}, equity='1000', cash='1000', buying_power='800', multiplier='1',
        observed_at=observed, valid_until=observed+timedelta(minutes=10),
        matched_protected_reservation=proof)
    return row, observed


def test_earlier_protected_order_bound_keeps_exact_instant_at_producer_boundary():
    row, observed = protected_account()
    assert row.status == model.OK and row.valid_until.utcoffset() == timedelta(hours=-4)
    current = sources._utc_row(row)
    assert current.valid_until == row.valid_until == observed+timedelta(minutes=1)
    assert current.valid_until.utcoffset() == timedelta(0)
    assert current.effective_status(observed) == model.OK
    assert current.effective_status(current.valid_until+timedelta(microseconds=1)) == model.FAIL
    snapshots.encode(model.Panel(now=observed, rows=[current]),
        context_sha256=CONTEXT, subjects=SUBJECTS)


def test_actual_full_builder_normalizes_aware_row_and_recovery_clocks(monkeypatch):
    from tests.sentinel.test_panel_postclose_feed_wait import build
    row, _ = protected_account()
    local = NOW.astimezone(timezone(timedelta(hours=-5)))
    extra = replace(row, key='protected_clock', as_of=local, valid_until=local+timedelta(seconds=20),
        recovery=model.RecoveryEvidence(phase='CLOCK_TEST', automatic=True,
            next_attempt_at=local+timedelta(seconds=10), deadline=local+timedelta(seconds=20)))
    page = build(monkeypatch, extra=[extra])
    for item in page.rows:
        assert all(v is None or v.utcoffset() == timedelta(0)
                   for v in (item.as_of, item.valid_until))
        if item.recovery is not None:
            assert all(v is None or v.utcoffset() == timedelta(0)
                       for v in (item.recovery.next_attempt_at, item.recovery.deadline))


def test_naive_full_builder_fact_is_a_controlled_refusal(monkeypatch):
    from tests.sentinel.test_panel_postclose_feed_wait import build
    bad = model.Row('unidentified', 'Unknown clock', 'OBSERVED', model.OK,
        as_of=NOW.replace(tzinfo=None))
    with pytest.raises(ValueError, match='source clock') as caught:
        build(monkeypatch, extra=[bad])
    assert observer_failure.classify(caught.value).code == 'VALIDATION_REFUSED'


def test_removed_full_producer_normalization_is_detected(monkeypatch):
    body = textwrap.dedent(inspect.getsource(sources.build_panel))
    guard = 'rows=[_utc_row(row) for row in rows]'
    assert body.count(guard) == 1
    namespace = {}
    exec(compile(body.replace(guard, 'rows=rows'), '<removed-producer-clock-freeze>', 'exec'),
        vars(sources), namespace)
    monkeypatch.setattr(sources, 'build_panel', namespace['build_panel'])
    with pytest.raises(AssertionError):
        test_actual_full_builder_normalizes_aware_row_and_recovery_clocks(monkeypatch)


def closing_feed(*, decision='2026-11-09', frontier='2026-11-06'):
    _, closed = calendar.session_window(decision)
    now = closed.astimezone(timezone.utc)+timedelta(minutes=9)
    opened = calendar.session_window(calendar.next_session(decision))[0]
    boundary = opened.astimezone(timezone.utc)-timedelta(microseconds=1)
    recovery = model.RecoveryEvidence(phase='SOURCE_FRONTIER', automatic=True, deadline=boundary)
    book = model.ShadowBook(session=frontier, cash='100', receivables='0', nav='100',
        pending_operations=0, holdings=[])
    rows = [model.Row('shadow_verification', 'Shadow', 'WAITING', model.WARN,
        as_of=now, required_current=True, valid_until=boundary, recovery=recovery),
        model.Row('book', 'Book', 'LAST ATTESTED', model.WARN,
            as_of=closed.astimezone(timezone.utc)-timedelta(days=3), required_current=True,
            valid_until=boundary, recovery=recovery, shadow_book=book)]
    worker = model.Row('shadow_worker', 'Worker', 'RUNNING', model.OK,
        as_of=now, required_current=True, valid_until=now+timedelta(seconds=60))
    original = model.feed_row(frontier=frontier, sessions_behind=1, ready=True,
        checks_passed=14, checks_total=14, as_of=now-timedelta(seconds=17),
        checked_at=now-timedelta(minutes=15))
    proof = waiting.from_rows(rows, worker, now=now)
    assert proof is not None
    projected = waiting.project(original, proof, frontier=frontier, sessions_behind=1,
        ready=True, now=now)
    return model.Panel(rows=[projected], now=now), boundary


@pytest.mark.parametrize('decision,frontier', [('2026-11-09', '2026-11-06'),
                                              ('2026-06-01', '2026-05-29')])
def test_calendar_wait_feed_enters_actual_snapshot_in_utc(decision, frontier):
    page, boundary = closing_feed(decision=decision, frontier=frontier)
    row = page.row('feed')
    assert row.status == model.WARN and row.valid_until == boundary
    assert row.valid_until.utcoffset() == timedelta(0)
    assert row.recovery.deadline == boundary
    value, signed = snapshots.encode(page, context_sha256=CONTEXT, subjects=SUBJECTS)
    assert snapshots.decode(value, signed, context_sha256=CONTEXT, now=page.now).panel.row(
        'feed').valid_until == boundary


def test_removed_calendar_producer_conversion_reproduces_exact_close_failure(monkeypatch):
    body = textwrap.dedent(inspect.getsource(waiting.from_rows))
    guard = '.astimezone(\n            timezone.utc)'
    assert body.count(guard) == 1
    namespace = {}
    exec(compile(body.replace(guard, ''), '<removed-close-producer-utc>', 'exec'),
         vars(waiting), namespace)
    monkeypatch.setattr(waiting, 'from_rows', namespace['from_rows'])
    page, boundary = closing_feed()
    assert page.row('feed').valid_until == boundary
    assert page.row('feed').valid_until.utcoffset() == timedelta(hours=-5)
    with pytest.raises(snapshots.SnapshotUnavailable, match='SNAPSHOT_ROW_CLOCK_INVALID'):
        snapshots.encode(page, context_sha256=CONTEXT, subjects=SUBJECTS)
    failure = observer_failure.failure('VALIDATION_REFUSED', 'OBSERVATION',
        error=snapshots.SnapshotUnavailable('SNAPSHOT_ROW_CLOCK_INVALID'))
    assert failure.fingerprint == '43d023f0f3cb71bd54fc32508458d01f2ecce0a3374d3f33fe6a109e1137d80e'


def test_removed_broker_clock_independence_is_detected(db, monkeypatch):
    body = textwrap.dedent(inspect.getsource(sources._runtime_valid_until))
    assert body.count('if broker_fact:') == 1
    namespace = {}
    exec(compile(body.replace('if broker_fact:', 'if False:'), '<restored-trading-wake>', 'exec'),
         vars(sources), namespace)
    monkeypatch.setattr(sources, '_runtime_valid_until', namespace['_runtime_valid_until'])
    with pytest.raises(AssertionError):
        test_fresh_account_and_broker_do_not_borrow_trading_wake(db, monkeypatch,
            {'state': 'RETRY_WAIT', 'retry_phase': 'REFRESH',
             'next_wake_at': NOW-timedelta(seconds=1)})


def test_removed_source_offset_normalization_is_detected(db, monkeypatch):
    body = textwrap.dedent(inspect.getsource(sources._utc))
    assert body.count('return dt.astimezone(timezone.utc)') == 1
    namespace = {}
    exec(compile(body.replace('return dt.astimezone(timezone.utc)', 'return dt'),
        '<removed-source-utc>', 'exec'), vars(sources), namespace)
    monkeypatch.setattr(sources, '_utc', namespace['_utc'])
    with pytest.raises(AssertionError):
        test_real_database_offset_timestamps_enter_signed_rows_in_utc(db, monkeypatch)


def publication_page(monkeypatch):
    from sentinel import source_publication_wait
    from sentinel.feed.rolling_contract import PriceWindow, digest
    from sentinel.feed.rolling_jobs import PreparationRequest
    from sentinel.panel import observer_codec, publication_wait, read_projection
    request = PreparationRequest(window=PriceWindow.through('2026-11-09'),
        strategy_sha256='a'*64, dependencies_sha256='b'*64).model_dump(mode='json')
    original = NOW+timedelta(days=2)
    record = [request, digest(request), 'READY', NOW-timedelta(minutes=40), original,
        NOW-timedelta(minutes=15), NOW-timedelta(minutes=25), 'active', NOW]
    deadline = source_publication_wait.deadline_from_record(record, now=NOW)
    opened = calendar.session_window('2026-11-10')[0]
    assert deadline == opened-timedelta(microseconds=1)
    assert deadline.utcoffset() == timedelta(hours=-5)
    proof = source_publication_wait.PublicationWaitProof('2026-11-09', deadline, original, NOW)
    monkeypatch.setattr(source_publication_wait, 'observe', lambda *a, **kw: proof)
    monkeypatch.setattr(read_projection, 'subject_for', lambda *a: 'a'*64)
    packed = publication_wait.observe('postgresql://isolated.invalid/private', False, 'a'*64)
    return model.Panel(now=NOW, rows=[observer_codec.row_from_observation(r) for r in packed['rows']]), deadline


def test_atomic_publication_next_open_enters_signed_rows_in_utc(monkeypatch):
    page, deadline = publication_page(monkeypatch)
    assert all(r.valid_until == deadline and r.valid_until.utcoffset() == timedelta(0)
               for r in page.rows)
    value, signed = snapshots.encode(page, context_sha256=CONTEXT, subjects=SUBJECTS)
    restored = snapshots.decode(value, signed, context_sha256=CONTEXT, now=NOW)
    assert all(r.valid_until == deadline for r in restored.panel.rows)


def test_removed_atomic_publication_conversion_is_detected(monkeypatch):
    monkeypatch.setattr(sources, '_utc', lambda value: value)
    page, _ = publication_page(monkeypatch)
    with pytest.raises(snapshots.SnapshotUnavailable, match='SNAPSHOT_ROW_CLOCK_INVALID'):
        snapshots.encode(page, context_sha256=CONTEXT, subjects=SUBJECTS)
