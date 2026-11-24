from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import threading

import pytest

from sentinel import alert_health, schema
from sentinel.automation import outbox
from sentinel.automation.model import (
    AckState,
    AlertState,
    AutomationRefused,
    ImmutableAlertChanged,
)
from sentinel.feed import store as feed_store
from tests.support.postgres import _EphemeralPostgres


def _renewal_row(**changes):
    from datetime import datetime, timedelta, timezone
    now = datetime(2026, 10, 30, 8, tzinfo=timezone.utc)
    proof = dict(schema="sentinel.backup-maintenance-progress/1", attempt="a" * 32,
                 started_at=int(now.timestamp()) - 60, deadline=int(now.timestamp()) + 3540,
                 system_identifier="7691913275518591014", image="sha256:" + "d" * 64,
                 predecessor_base="base-20261029T072734Z", base_backup="base-20261029T072734Z",
                 phase="FAILED")
    proof.update(changes)
    return [proof, now, True, "7691913275518591014", now - timedelta(days=1),
            now + timedelta(seconds=1), None, None, False]


def test_backup_renewal_warning_deduplicates_the_base_not_five_minute_retry():
    first = outbox._backup_renewal_warning(_renewal_row())
    retry = outbox._backup_renewal_warning(_renewal_row(attempt="b" * 32))
    assert first["idempotency_key"] == retry["idempotency_key"]
    assert first["event_type"] == "BACKUP_RENEWAL_FAILED" and first["severity"] == "WARN"
    assert "journal" in first["payload"]["reason"]
    assert first["payload"]["attempt"] != retry["payload"]["attempt"]


@pytest.mark.parametrize("field,value", [
    ("schema", "future-schema"), ("attempt", "not-an-attempt"),
    ("phase", "BASE_BACKUP"), ("phase", "COMPLETE"),
    ("system_identifier", "7777777777777777777"), ("system_identifier", None),
    ("image", "mutable:latest"), ("predecessor_base", "../foreign"),
    ("base_backup", False), ("started_at", True), ("started_at", "1"),
    ("deadline", False), ("deadline", 0), ("deadline", 2**63),
])
def test_backup_warning_rejects_untyped_or_foreign_progress(field, value):
    assert outbox._backup_renewal_warning(_renewal_row(**{field: value})) is None


@pytest.mark.parametrize("fault", ["digest", "before-policy", "future", "extra-field", "missing-field",
                                   "no-policy", "naive-time", "not-a-document"])
def test_backup_warning_requires_authentic_current_policy_observation(fault):
    from datetime import timedelta
    row = _renewal_row()
    if fault == "digest": row[2] = False
    elif fault == "before-policy": row[4] = row[1] + timedelta(seconds=1)
    elif fault == "future": row[5] = row[1] - timedelta(seconds=1)
    elif fault == "extra-field": row[0]["unreviewed"] = True
    elif fault == "missing-field": row[0].pop("attempt")
    elif fault == "no-policy": row[4] = None
    elif fault == "naive-time": row[1] = row[1].replace(tzinfo=None)
    else: row[0] = []
    assert outbox._backup_renewal_warning(row) is None


def _verified_successor(system):
    return dict(schema="sentinel.verified-base/1", physical_verified=True,
                metadata_sha256="c" * 64, base_backup="base-20261030T080000Z",
                marker="sentinel-backup-20261030T080000Z-123", marker_lsn="0/1000000",
                marker_wal="000000010000000000000001", system_identifier=system,
                xid8_before="100", xid8_after="101")


@pytest.mark.parametrize("fault", [None, "digest", "foreign", "unverified", "untyped", "older",
                                   "incomplete", "bad-marker", "regressed-xid"])
def test_only_actual_later_verified_successor_suppresses_old_failure(fault):
    from datetime import timedelta
    row = _renewal_row()
    row[6], row[7], row[8] = _verified_successor(row[3]), row[1], True
    if fault == "digest": row[8] = False
    elif fault == "foreign": row[6]["system_identifier"] = "7777777777777777777"
    elif fault == "unverified": row[6]["physical_verified"] = False
    elif fault == "untyped": row[6]["physical_verified"] = 1
    elif fault == "older": row[7] = row[1] - timedelta(seconds=1)
    elif fault == "incomplete": row[6].pop("metadata_sha256")
    elif fault == "bad-marker": row[6]["marker"] = "unknown"
    elif fault == "regressed-xid": row[6]["xid8_after"] = "99"
    assert (outbox._backup_renewal_warning(row) is None) is (fault is None)


def test_backup_warning_foreign_system_guard_falsifier():
    import inspect
    source = inspect.getsource(outbox._backup_renewal_warning)
    guard = 'proof.get("system_identifier") != system'
    assert guard in source
    namespace = dict(vars(outbox))
    exec(compile(source.replace(guard, "False"), "removed-current-system-guard", "exec"), namespace)
    mutant = namespace["_backup_renewal_warning"]
    foreign = _renewal_row(system_identifier="7777777777777777777")
    assert outbox._backup_renewal_warning(foreign) is None
    with pytest.raises(AssertionError):
        assert mutant(foreign) is None


def _insert_backup_notice_progress(conn, *, attempt="a" * 32, phases=("BASE_BACKUP", "FAILED"),
                                   authentic=True, observed=None, **changes):
    from psycopg.types.json import Jsonb
    now, system = conn.execute("SELECT clock_timestamp(),system_identifier::text "
                               "FROM pg_control_system()").fetchone()
    observed = now if observed is None else observed
    proof = _renewal_row()[0]
    proof.update(system_identifier=system, attempt=attempt,
                 started_at=int(observed.timestamp()) - 60, deadline=int(observed.timestamp()) + 3540)
    proof.update(changes)
    for phase in phases:
        proof["phase"] = phase
        conn.execute("WITH v AS (SELECT %s::jsonb AS proof) INSERT INTO sentinel_backup_evidence "
            "(kind,evidence_sha256,proof,observed_at) SELECT 'MAINTENANCE_PROGRESS',"
            "CASE WHEN %s THEN encode(sha256(convert_to(proof::text,'UTF8')),'hex') ELSE repeat('0',64) END,"
            "proof,%s FROM v", (Jsonb(proof), authentic, observed))
    conn.commit()
    return proof


def test_real_backup_renewal_failure_reconstructed_once_across_retries_and_restart(conn):
    first = _insert_backup_notice_progress(conn)
    outbox._reconstruct_missing_transition_alerts(conn)
    conn.commit()
    _insert_backup_notice_progress(conn, attempt="b" * 32)
    for _ in range(2):
        outbox._reconstruct_missing_transition_alerts(conn)
        conn.commit()
    rows = conn.execute("SELECT event_type,severity,payload FROM sentinel_alert_outbox").fetchall()
    assert len(rows) == 1 and rows[0][:2] == ("BACKUP_RENEWAL_FAILED", "WARN")
    assert rows[0][2]["attempt"] == first["attempt"]
    assert conn.execute("SELECT count(*) FROM sentinel_commands").fetchone()[0] == 0


@pytest.mark.parametrize("phases", [("BASE_BACKUP",), ("BASE_BACKUP", "VERIFY_CHAIN", "COMPLETE")])
def test_real_newer_maintenance_progress_never_reconstructs_old_failed_renewal(conn, phases):
    _insert_backup_notice_progress(conn)
    _insert_backup_notice_progress(conn, attempt="b" * 32, phases=phases)
    outbox._reconstruct_missing_transition_alerts(conn)
    conn.commit()
    assert conn.execute("SELECT count(*) FROM sentinel_alert_outbox").fetchone()[0] == 0


@pytest.mark.parametrize("fault", ["digest", "foreign", "historical", "future", "untyped", "oversized"])
def test_real_bad_backup_notice_evidence_cannot_block_unrelated_critical_delivery(conn, fault):
    from datetime import timedelta
    kwargs = {}
    if fault == "digest": kwargs["authentic"] = False
    elif fault == "foreign": kwargs["system_identifier"] = "7777777777777777777"
    elif fault in {"historical", "future"}:
        now = conn.execute("SELECT clock_timestamp()").fetchone()[0]
        kwargs["observed"] = now + timedelta(hours=-1 if fault == "historical" else 1)
    elif fault == "untyped": kwargs["started_at"] = True
    else: kwargs["unreviewed"] = "x" * 9000
    _insert_backup_notice_progress(conn, **kwargs)
    critical = outbox.enqueue(conn, idempotency_key="unrelated-critical", event_type="CRITICAL_INCIDENT",
                              severity="CRITICAL", payload={"reason": "independent current incident"})
    claimed = outbox.claim_next(conn, holder_id="independent-dispatcher")
    assert claimed.alert_id == critical.alert_id
    assert conn.execute("SELECT count(*) FROM sentinel_alert_outbox "
                        "WHERE event_type='BACKUP_RENEWAL_FAILED'").fetchone()[0] == 0


def test_real_verified_successor_suppresses_obsolete_failed_renewal(conn):
    from psycopg.types.json import Jsonb
    failed = _insert_backup_notice_progress(conn)
    successor = _verified_successor(failed["system_identifier"])
    conn.execute("WITH v AS (SELECT %s::jsonb AS proof) INSERT INTO sentinel_backup_evidence "
        "(kind,evidence_sha256,proof) SELECT 'BASE_BACKUP',"
        "encode(sha256(convert_to(proof::text,'UTF8')),'hex'),proof FROM v", (Jsonb(successor),))
    conn.commit()
    outbox._reconstruct_missing_transition_alerts(conn)
    conn.commit()
    assert conn.execute("SELECT count(*) FROM sentinel_alert_outbox").fetchone()[0] == 0


@pytest.fixture(scope="module")
def pg():
    try:
        server = _EphemeralPostgres()
        server.start()
    except Exception as exc:                                  # noqa: BLE001
        pytest.skip(f"ephemeral Postgres unavailable: {exc}")
    try:
        yield server
    finally:
        server.stop()


@pytest.fixture()
def conn(pg):
    connection = feed_store.connect(pg.sync_dsn)
    with connection.cursor() as cur:
        # This server belongs solely to this module's disposable fixture.
        # Current trigger functions must not survive a table-only reset.
        cur.execute('DROP SCHEMA public CASCADE')
        cur.execute('CREATE SCHEMA public')
    connection.commit()
    schema.ensure_schema(connection)
    feed_store.migrate_schema(connection)
    from sentinel.panel import operational_schema
    operational_schema.install(connection)
    connection.commit()
    yield connection
    connection.close()


def test_enqueue_is_idempotent_and_content_immutable(conn) -> None:
    first = outbox.enqueue(
        conn, idempotency_key="cycle-a:kill", event_type="KILL_ENGAGED",
        severity="CRITICAL", payload={"generation": 7})
    duplicate = outbox.enqueue(
        conn, idempotency_key="cycle-a:kill", event_type="KILL_ENGAGED",
        severity="CRITICAL", payload={"generation": 7})

    assert duplicate == first
    with pytest.raises(ImmutableAlertChanged):
        outbox.enqueue(
            conn, idempotency_key="cycle-a:kill", event_type="KILL_ENGAGED",
            severity="CRITICAL", payload={"generation": 8})
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM sentinel_alert_outbox")
        assert cur.fetchone()[0] == 1


def test_completed_predecessor_wait_preserves_legacy_alert_across_new_permits(conn):
    """Reproduce the real immutable-key crash without editing its old evidence."""
    import asyncio
    import inspect
    import textwrap
    from sentinel import automation_runtime
    from test_automation_runtime import config,production,completed_predecessor_wait

    cfg=config();runtime=production(cfg)
    original=completed_predecessor_wait(cfg,generation=86,fence=118)
    key=f'cycle:{original.cycle.cycle_id}:WAITING:{original.reason}'
    first=outbox.enqueue(conn,idempotency_key=key,event_type='AUTOMATION_WAITING',
        severity='WARN',payload={
            'cycle_id':original.cycle.cycle_id,'action':'WAITING','reason':original.reason,
            'state':'SUCCEEDED','control_generation':86,'fence_token':118,
        },max_attempts=cfg.alert_max_attempts)
    def snapshot():
        return conn.execute('SELECT to_jsonb(a) FROM sentinel_alert_outbox a WHERE alert_id=%s',
                            (first.alert_id,)).fetchone()[0]
    before=snapshot()
    for generation,fence in ((86,118),(86,118),(86,119),(87,120)):
        result=completed_predecessor_wait(cfg,generation=generation,fence=fence)
        assert asyncio.run(runtime.notify(conn,result)) is None
        assert snapshot()==before
    assert conn.execute('SELECT count(*) FROM sentinel_alert_outbox').fetchone()[0]==1

    # Disable only the new quiet branch. The unchanged native enqueue must
    # reproduce the original collision, proving the test reaches that failure.
    source=textwrap.dedent(inspect.getsource(automation_runtime.ProductionAutomation.notify))
    guard='if (result.action.value == "WAITING"'
    assert source.count(guard)==1
    scope={}
    exec(compile(source.replace(guard,'if (False and result.action.value == "WAITING"',1),
                 '<removed-completed-predecessor-quiet-guard>','exec'),
         vars(automation_runtime),scope)
    reacquired=completed_predecessor_wait(cfg,generation=86,fence=119)
    with pytest.raises(ImmutableAlertChanged,match='different content'):
        asyncio.run(scope['notify'](runtime,conn,reacquired))
    assert snapshot()==before
    assert conn.execute('SELECT count(*) FROM sentinel_alert_outbox').fetchone()[0]==1


def test_alert_adapters_come_from_an_explicit_registry() -> None:
    adapter = outbox.LogAlertAdapter()
    registry = outbox.AlertAdapterRegistry({"log": adapter})

    assert registry.get("log") is adapter
    with pytest.raises(AutomationRefused, match="explicit registry"):
        registry.get("environment.import.path")


@pytest.mark.parametrize("reconstruct", [False, True])
def test_real_retry_transition_survives_live_notification_and_reconstruction(conn, reconstruct, monkeypatch):
    import asyncio
    from sentinel.automation.model import SourceDataPending, TickAction
    from sentinel.automation_resilience import RecoveryAutomationService
    from test_automation_service import (AFTER_WEDNESDAY_CLOSE, config, enable,
                                         prepare_result, recovery_success, execution_success)

    async def pending(_context):
        raise SourceDataPending("provider has not completed the source join")

    cfg = config()
    enable(conn, cfg)
    service = RecoveryAutomationService(
        config=cfg, holder_id="notification-writer", refresh=pending,
        prepare=prepare_result, recover=recovery_success, execute=execution_success)
    asyncio.run(service.tick(conn, now=AFTER_WEDNESDAY_CLOSE))
    result = asyncio.run(service.tick(conn, now=AFTER_WEDNESDAY_CLOSE))
    assert result.action is TickAction.RETRY_SCHEDULED
    decoded = []
    event_alert = outbox._cycle_event_alert

    def record_event_alert(row):
        decoded.append(row)
        return event_alert(row)

    monkeypatch.setattr(outbox, "_cycle_event_alert", record_event_alert)
    for _ in range(2):
        if reconstruct:
            outbox._reconstruct_missing_transition_alerts(conn)
        else:
            outbox.enqueue_cycle_transition_alert(conn, cycle_id=result.cycle.cycle_id,
                                                 state="RETRY_WAIT")
    row = conn.execute("SELECT payload FROM sentinel_alert_outbox WHERE event_type='AUTOMATION_RETRY_SCHEDULED'").fetchall()
    assert len(row) == 1
    assert row[0][0]["detail"]["retry_phase"] == "REFRESH"
    assert len(decoded) == (1 if reconstruct else 2)


def test_reconstruct_only_missing_control_alerts(conn, monkeypatch):
    with conn.cursor() as cur:
        cur.execute("""INSERT INTO sentinel_automation_events
            (generation,action,actor,reason,detail)
            VALUES (1,'KILL_ENGAGED','operator','first','{}')""")
    conn.commit()
    first = outbox.enqueue_latest_kill_alert(conn)
    decoded = []
    rebuild = outbox._control_event_alert

    def record_control_event(row):
        decoded.append(row)
        return rebuild(row)

    monkeypatch.setattr(outbox, '_control_event_alert', record_control_event)
    outbox._reconstruct_missing_transition_alerts(conn)
    assert decoded == []
    conn.execute("""INSERT INTO sentinel_automation_events
        (generation,action,actor,reason,detail)
        VALUES (2,'KILL_ENGAGED','operator','second','{}')""")
    conn.commit()
    outbox._reconstruct_missing_transition_alerts(conn)
    outbox._reconstruct_missing_transition_alerts(conn)
    assert [row[1] for row in decoded] == [2]
    ids = conn.execute('SELECT alert_id FROM sentinel_alert_outbox ORDER BY created_at').fetchall()
    assert len(ids) == 2 and ids[0] == (first.alert_id,)


@pytest.mark.parametrize('adopt', [False, True])
@pytest.mark.parametrize('reconstruct', [False, True])
def test_new_proved_unsent_missed_window_is_warning_across_alert_recovery(
        conn, adopt, reconstruct):
    from sentinel.automation import store
    from sentinel.automation.model import AutomationConfig, CycleState
    from tests.sentinel.test_automation_store import cycle_spec, enable

    cfg = AutomationConfig(publication_delay_seconds=0, execution_delay_seconds=0)
    control = enable(conn, cfg)
    first = store.acquire_lease(conn, holder_id='missed-window-a', lease_seconds=30)
    cycle = store.create_cycle(conn, permit=first, spec=cycle_spec(control, cfg))
    if adopt:
        cycle = store.transition_cycle(
            conn, permit=first, cycle_id=cycle.cycle_id,
            to_state=CycleState.PREPARING)
        store.engage_kill(conn, actor='test', reason='new generation')
        store.release_kill(conn, expected_binding=control.binding,
                           actor='test', reason='resume')
        second = store.acquire_lease(
            conn, holder_id='missed-window-b', lease_seconds=30)
        cycle = store.adopt_cycle(
            conn, permit=second, cycle_id=cycle.cycle_id,
            to_state=CycleState.SUPERSEDED,
            failure_code='CONTROL_GENERATION_SUPERSEDED')
    else:
        cycle = store.transition_cycle(
            conn, permit=first, cycle_id=cycle.cycle_id,
            to_state=CycleState.SUPERSEDED,
            failure_code='MISSED_EXECUTION_WINDOW')
    event = conn.execute(
        "SELECT detail FROM sentinel_automation_cycle_events "
        "WHERE cycle_id=%s AND to_state='SUPERSEDED' ORDER BY seq DESC LIMIT 1",
        (cycle.cycle_id,)).fetchone()[0]
    assert event['missed_window_no_send']['schema'] == 'sentinel.missed-window-no-send/1'
    assert event['failure_code'] == (
        'CONTROL_GENERATION_SUPERSEDED' if adopt else 'MISSED_EXECUTION_WINDOW')

    if reconstruct:
        outbox._reconstruct_missing_transition_alerts(conn)
        conn.commit()
    else:
        outbox.enqueue_cycle_transition_alert(
            conn, cycle_id=cycle.cycle_id, state='SUPERSEDED')
    rows = conn.execute(
        "SELECT idempotency_key,event_type,severity,payload FROM sentinel_alert_outbox "
        "WHERE event_type='AUTOMATION_SUPERSEDED'").fetchall()
    assert len(rows) == 1
    assert rows[0][0].startswith('cycle-event:')
    assert rows[0][2] == 'WARN'
    assert rows[0][3]['detail'] == event


def test_missed_window_alert_is_critical_when_journal_proof_fails(conn, monkeypatch):
    from sentinel.automation import store, unsent_recovery
    from sentinel.automation.model import AutomationConfig, CycleState
    from tests.sentinel.test_automation_store import cycle_spec, enable

    cfg = AutomationConfig(publication_delay_seconds=0, execution_delay_seconds=0)
    control = enable(conn, cfg)
    permit = store.acquire_lease(conn, holder_id='uncertain-window', lease_seconds=30)
    cycle = store.create_cycle(conn, permit=permit, spec=cycle_spec(control, cfg))
    # A durable transport event invalidates no-send even if the latest cycle
    # row still says DISCOVERED and has no recorded attempt.
    conn.execute(
        "INSERT INTO sentinel_automation_cycle_events "
        "(cycle_id,from_state,to_state,control_generation,fence_token,detail) "
        "VALUES (%s,'EXECUTING','RECONCILING',%s,%s,'{}'::jsonb)",
        (cycle.cycle_id, permit.control_generation, permit.fence_token))
    conn.commit()
    retired = store.transition_cycle(
        conn, permit=permit, cycle_id=cycle.cycle_id,
        to_state=CycleState.SUPERSEDED,
        failure_code='MISSED_EXECUTION_WINDOW')
    alert = outbox.enqueue_cycle_transition_alert(
        conn, cycle_id=retired.cycle_id, state='SUPERSEDED')
    assert alert.severity == 'CRITICAL'
    assert 'missed_window_no_send' not in alert.payload['detail']

    # Removing the journal check would make this exact case falsely WARN.
    monkeypatch.setattr(unsent_recovery, 'require_unsent', lambda *_a, **_k: None)
    with pytest.raises(AssertionError):
        assert store._missed_window_alert_witness(
            conn, cycle, store.load_control(conn),
            failure_code='MISSED_EXECUTION_WINDOW') is None


@pytest.mark.parametrize('state,attempts,code', [
    ('EXECUTING', 0, 'MISSED_EXECUTION_WINDOW'),
    ('DISCOVERED', 1, 'MISSED_EXECUTION_WINDOW'),
    ('DISCOVERED', 0, 'UNREVIEWED_FAILURE'),
])
def test_transport_or_ambiguous_cycle_cannot_earn_no_send_alert_witness(
        conn, monkeypatch, state, attempts, code):
    from sentinel.automation import store, unsent_recovery
    from sentinel.automation.model import AutomationConfig, CycleState
    from tests.sentinel.test_automation_store import cycle_spec, enable

    cfg = AutomationConfig(publication_delay_seconds=0, execution_delay_seconds=0)
    control = enable(conn, cfg)
    permit = store.acquire_lease(conn, holder_id='unsafe-window', lease_seconds=30)
    cycle = store.create_cycle(conn, permit=permit, spec=cycle_spec(control, cfg))
    candidate = cycle.model_copy(update={
        'state': CycleState(state), 'attempt_count': attempts})
    monkeypatch.setattr(unsent_recovery, 'require_unsent', lambda *_a, **_k: None)
    assert store._missed_window_alert_witness(
        conn, candidate, control, failure_code=code) is None


@pytest.mark.parametrize('fault', [
    'missing', 'wrong-cycle', 'wrong-state', 'attempt', 'journal', 'extra',
])
def test_old_or_malformed_missed_window_event_stays_critical(fault):
    detail = {'failure_code': 'CONTROL_GENERATION_SUPERSEDED',
              'missed_window_no_send': {
                  'schema': 'sentinel.missed-window-no-send/1',
                  'cycle_id': 'old-cycle', 'from_state': 'PREPARING',
                  'attempt_count': 0,
                  'journal': 'NO_TRANSPORT_EVENT_OR_COMMAND'}}
    if fault == 'missing':
        detail.pop('missed_window_no_send')
    elif fault == 'wrong-cycle':
        detail['missed_window_no_send']['cycle_id'] = 'other-cycle'
    elif fault == 'wrong-state':
        detail['missed_window_no_send']['from_state'] = 'EXECUTING'
    elif fault == 'attempt':
        detail['missed_window_no_send']['attempt_count'] = 1
    elif fault == 'journal':
        detail['missed_window_no_send']['journal'] = 'UNKNOWN'
    else:
        detail['missed_window_no_send']['extra'] = True
    alert = outbox._cycle_event_alert(
        (101, 'old-cycle', 'SUPERSEDED', 2, 7, detail))
    assert alert['severity'] == 'CRITICAL'


@pytest.mark.parametrize('reconstruct', [False, True, 'completion'])
@pytest.mark.parametrize('deadline_risk', [False, True])
def test_closing_frontier_wait_is_quiet_in_direct_and_reconstructed_outbox_unless_deadline_risk(
        conn, reconstruct, deadline_risk, monkeypatch):
    import asyncio
    from datetime import timedelta
    from sentinel.automation.model import ClosingDataPending, TickAction
    from sentinel.automation import notification_completion
    from sentinel.automation_resilience import RecoveryAutomationService
    from tests.sentinel.test_automation_service import (
        AFTER_WEDNESDAY_CLOSE, config, enable, prepare_result, recovery_success, execution_success,
    )

    async def pending(_context):
        raise ClosingDataPending('the source-final closing frontier is not ready',
            publisher_deadline_at=(AFTER_WEDNESDAY_CLOSE + timedelta(seconds=5)
                if deadline_risk else None))

    if reconstruct == 'completion':
        _install_notification_ledger(conn, monkeypatch)
    cfg = config()
    enable(conn, cfg)
    worker = RecoveryAutomationService(config=cfg, holder_id='closing-notification-writer',
        refresh=pending, prepare=prepare_result, recover=recovery_success, execute=execution_success)
    asyncio.run(worker.tick(conn, now=AFTER_WEDNESDAY_CLOSE))
    result = asyncio.run(worker.tick(conn, now=AFTER_WEDNESDAY_CLOSE))
    assert result.action is TickAction.RETRY_SCHEDULED
    event_before = conn.execute('SELECT detail FROM sentinel_automation_cycle_events '
        "WHERE cycle_id=%s AND to_state='RETRY_WAIT' ORDER BY seq DESC LIMIT 1",
        (result.cycle.cycle_id,)).fetchone()[0]
    assert ('closing_data_wait' in event_before['diagnostic']) is (not deadline_risk)
    if reconstruct == 'completion':
        decoded = []
        original = outbox._cycle_event_alert

        def classify(row):
            decoded.append(row[0])
            return original(row)

        monkeypatch.setattr(outbox, '_cycle_event_alert', classify)
    for _ in range(2):
        if reconstruct:
            outbox._reconstruct_missing_transition_alerts(conn, completion=reconstruct == 'completion')
            conn.commit()
        else:
            alert = outbox.enqueue_cycle_transition_alert(conn,
                cycle_id=result.cycle.cycle_id, state='RETRY_WAIT')
            assert (alert is not None) is deadline_risk
    assert conn.execute("SELECT count(*) FROM sentinel_alert_outbox "
        "WHERE event_type='AUTOMATION_RETRY_SCHEDULED'").fetchone()[0] == int(deadline_risk)
    assert conn.execute('SELECT detail FROM sentinel_automation_cycle_events '
        "WHERE cycle_id=%s AND to_state='RETRY_WAIT' ORDER BY seq DESC LIMIT 1",
        (result.cycle.cycle_id,)).fetchone()[0] == event_before
    if reconstruct == 'completion':
        assert len(decoded) == 1
        completed = conn.execute(f"SELECT seq,alert_key FROM {notification_completion.TABLE} "
                                 "WHERE source='CYCLE'").fetchall()
        assert len(completed) == 1 and completed[0][0] == decoded[0]
        assert (completed[0][1] is not None) is deadline_risk


def _install_notification_ledger(conn, monkeypatch):
    from sentinel import operational_schema

    conn.rollback()
    monkeypatch.setenv('SENTINEL_PUBLICATION_RECEIPT_KEY', 'notification-private-test-key' * 2)
    return operational_schema.install_quiescent(conn)


def _control_event(conn, reason, *, before_activation=False):
    return conn.execute(
        "INSERT INTO sentinel_automation_events(generation,action,actor,reason,detail,at) "
        "SELECT 1,'KILL_ENGAGED','private-test',%s,'{}',"
        "CASE WHEN %s THEN web_push_activated_at-interval '1 second' ELSE clock_timestamp() END "
        "FROM sentinel_notification_policy WHERE id=1 RETURNING seq",
        (reason, before_activation),
    ).fetchone()[0]


@pytest.mark.parametrize('recovery', [False, True])
@pytest.mark.parametrize('conflict', ['alert_id', 'idempotency_key'])
def test_conflicting_outbox_identity_does_not_complete_recovery(conn, monkeypatch, recovery, conflict):
    from sentinel.automation.notification_completion import TABLE

    _install_notification_ledger(conn, monkeypatch)
    seq = _control_event(conn, 'pending control event')
    key = f'control-event:{seq}'
    other_key = 'different-event'
    stored_id = outbox._alert_id(key if conflict == 'alert_id' else other_key)
    stored_key = key if conflict == 'idempotency_key' else other_key
    conn.execute(
        "INSERT INTO sentinel_alert_outbox"
        " (alert_id,idempotency_key,schema_version,event_type,severity,payload,state,max_attempts)"
        " VALUES (%s,%s,1,'AUTOMATION_KILL_ENGAGED','CRITICAL','{}','PENDING',8)",
        (stored_id, stored_key),
    )
    conn.commit()

    with pytest.raises(ImmutableAlertChanged, match='stored alert ID and idempotency key disagree'):
        if recovery:
            outbox.claim_next(conn, holder_id='private-dispatcher')
        else:
            outbox.enqueue(conn, idempotency_key=key, event_type='AUTOMATION_KILL_ENGAGED',
                           severity='CRITICAL', payload={})

    assert conn.execute(f'SELECT count(*) FROM {TABLE}').fetchone() == (0,)
    assert conn.execute('SELECT alert_id,idempotency_key,state FROM sentinel_alert_outbox').fetchall() == [
        (stored_id, stored_key, 'PENDING')]


def test_completion_finds_late_lower_sequence_and_keeps_original_outbox(conn, pg, monkeypatch):
    from sentinel.automation.notification_completion import TABLE

    _install_notification_ledger(conn, monkeypatch)
    excluded = _control_event(conn, 'before activation', before_activation=True)
    conn.commit()
    with feed_store.connect(pg.sync_dsn) as delayed:
        lower = _control_event(delayed, 'late commit')
        newer = _control_event(conn, 'already notified')
        conn.commit()
        existing = outbox.enqueue_latest_kill_alert(conn)
        first = outbox.claim_next(conn, holder_id='private-one')
        assert first.alert_id == existing.alert_id
        assert conn.execute(f'SELECT seq FROM {TABLE}').fetchall() == [(newer,)]
        outbox.mark_delivered(conn, alert_id=first.alert_id, holder_id='private-one',
                              attempt=first.attempt_count)
        delayed.commit()
    second = outbox.claim_next(conn, holder_id='private-two')
    assert second.idempotency_key == f'control-event:{lower}'
    assert lower < newer
    assert conn.execute(f'SELECT seq FROM {TABLE} ORDER BY seq').fetchall() == [(lower,), (newer,)]
    assert conn.execute("SELECT 1 FROM sentinel_alert_outbox WHERE idempotency_key=%s",
                        (f'control-event:{excluded}',)).fetchone() is None
    conn.execute("UPDATE sentinel_automation_events SET reason='changed source version' WHERE seq=%s",
                 (newer,))
    conn.commit()
    assert outbox.claim_next(conn, holder_id='private-updated-version') is None
    assert conn.execute(f'SELECT count(*) FROM {TABLE} WHERE seq=%s', (newer,)).fetchone() == (2,)
    assert outbox.load_alert(conn, existing.alert_id).payload == existing.payload


def test_completion_crash_replays_whole_batch_and_dispatchers_converge(conn, pg, monkeypatch):
    from sentinel.automation.notification_completion import TABLE

    _install_notification_ledger(conn, monkeypatch)
    for index in range(3):
        _control_event(conn, str(index))
    conn.commit()
    monkeypatch.setattr(outbox, '_NOTIFICATION_BATCH', 2)
    outbox._reconstruct_missing_transition_alerts(conn, completion=True)
    assert conn.execute(f'SELECT count(*) FROM {TABLE}').fetchone()[0] == 2
    assert conn.execute('SELECT count(*) FROM sentinel_alert_outbox').fetchone()[0] == 2
    conn.rollback()
    assert conn.execute(f'SELECT count(*) FROM {TABLE}').fetchone()[0] == 0
    assert conn.execute('SELECT count(*) FROM sentinel_alert_outbox').fetchone()[0] == 0
    conn.rollback()

    barrier = threading.Barrier(2)
    classify = outbox._control_event_alert

    def classify_shared_event(row):
        if row[4] == '0':
            barrier.wait(timeout=5)
        return classify(row)

    monkeypatch.setattr(outbox, '_control_event_alert', classify_shared_event)

    def claim(index):
        with feed_store.connect(pg.sync_dsn) as worker:
            return outbox.claim_next(worker, holder_id=f'private-dispatcher-{index}')

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = list(pool.map(claim, range(2)))
    assert first.alert_id != second.alert_id
    third = outbox.claim_next(conn, holder_id='private-third')
    assert third.alert_id not in {first.alert_id, second.alert_id}
    assert conn.execute(f'SELECT count(*) FROM {TABLE}').fetchone()[0] == 3
    assert conn.execute('SELECT count(*) FROM sentinel_alert_outbox').fetchone()[0] == 3


def test_completion_catalog_refuses_missing_or_altered_guards(conn, monkeypatch):
    from sentinel import operational_catalog, operational_schema
    from sentinel.automation import notification_completion as completion

    assert not completion.require_schema(conn, allow_absent=True)
    with pytest.raises(operational_catalog.OperationalCatalogRefused, match='CATALOG_PARTIAL'):
        completion.require_schema(conn)
    original = _install_notification_ledger(conn, monkeypatch)
    assert completion.require_schema(conn)
    conn.rollback()
    assert operational_schema.install_quiescent(conn) == original
    conn.execute(f'ALTER TABLE {completion.TABLE} DISABLE TRIGGER {completion.FUNCTION}')
    with pytest.raises(operational_catalog.OperationalCatalogRefused, match='CATALOG_CHANGED'):
        completion.require_schema(conn, allow_absent=True)
    conn.rollback()
    conn.execute(f'DROP TABLE {completion.TABLE}')
    with pytest.raises(operational_catalog.OperationalCatalogRefused, match='ORPHANED'):
        completion.require_schema(conn, allow_absent=True)
    conn.rollback()


def test_retry_backoff_dead_letter_and_ack_are_durable(conn) -> None:
    alert = outbox.enqueue(
        conn, idempotency_key="retry-me", event_type="BROKER_UNKNOWN",
        severity="CRITICAL", payload={"client_key": "k"}, max_attempts=2)
    first = outbox.claim_next(conn, holder_id="alerter", claim_seconds=30)
    assert first is not None
    assert first.alert_id == alert.alert_id
    assert first.state is AlertState.DELIVERING
    assert first.attempt_count == 1

    retry = outbox.mark_failed(
        conn, alert_id=alert.alert_id, holder_id="alerter",
        attempt=first.attempt_count,
        error="temporary adapter outage", retry_base_seconds=10,
        retry_max_seconds=60)
    assert retry.state is AlertState.PENDING
    with conn.cursor() as cur:
        cur.execute(
            "SELECT next_attempt_at > clock_timestamp()+INTERVAL '9 seconds'"
            " FROM sentinel_alert_outbox WHERE alert_id=%s", (alert.alert_id,))
        assert cur.fetchone()[0] is True
        cur.execute(
            "UPDATE sentinel_alert_outbox SET"
            " next_attempt_at=clock_timestamp()-INTERVAL '1 second'"
            " WHERE alert_id=%s", (alert.alert_id,))
    conn.commit()

    second = outbox.claim_next(conn, holder_id="alerter", claim_seconds=30)
    assert second is not None and second.attempt_count == 2
    dead = outbox.mark_failed(
        conn, alert_id=alert.alert_id, holder_id="alerter",
        attempt=second.attempt_count,
        error="credentials explicitly rejected", retry_base_seconds=10,
        retry_max_seconds=60, retryable=False)
    assert dead.state is AlertState.DEAD_LETTER

    acknowledged = outbox.acknowledge(
        conn, alert_id=alert.alert_id, actor="operator",
        acknowledgement="investigating adapter")
    assert acknowledged.ack_state is AckState.ACKNOWLEDGED
    assert outbox.acknowledge(
        conn, alert_id=alert.alert_id, actor="operator",
        acknowledgement="investigating adapter") == acknowledged

    with conn.cursor() as cur:
        cur.execute(
            "SELECT action FROM sentinel_alert_delivery_events"
            " WHERE alert_id=%s ORDER BY seq", (alert.alert_id,))
        assert [row[0] for row in cur.fetchall()] == [
            "CLAIMED", "RETRY_SCHEDULED", "CLAIMED", "DEAD_LETTERED"]


def test_expired_delivery_claim_is_recovered_with_same_idempotency_key(conn) -> None:
    alert = outbox.enqueue(
        conn, idempotency_key="stable-remote-key", event_type="LEASE_LOST",
        severity="ERROR", payload={"fence": 4})
    first = outbox.claim_next(conn, holder_id="dead-worker", claim_seconds=30)
    assert first is not None
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE sentinel_alert_outbox SET"
            " delivery_expires_at=clock_timestamp()-INTERVAL '1 second'"
            " WHERE alert_id=%s", (alert.alert_id,))
    conn.commit()

    recovered = outbox.claim_next(
        conn, holder_id="replacement", claim_seconds=30)

    assert recovered is not None
    assert recovered.idempotency_key == "stable-remote-key"
    assert recovered.attempt_count == 2
    assert recovered.delivery_holder == "replacement"


def test_repeated_crash_after_claim_remains_recoverable(conn) -> None:
    alert = outbox.enqueue(
        conn, idempotency_key="crash-after-every-claim",
        event_type="AUTOMATION_BLOCKED", severity="CRITICAL", payload={},
        max_attempts=2)

    first = outbox.claim_next(
        conn, holder_id="crashed-first", claim_seconds=30)
    assert first is not None and first.attempt_count == 1
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE sentinel_alert_outbox SET"
            " delivery_expires_at=clock_timestamp()-INTERVAL '1 second'"
            " WHERE alert_id=%s", (alert.alert_id,))
    conn.commit()

    second = outbox.claim_next(
        conn, holder_id="crashed-second", claim_seconds=30)
    assert second is not None and second.attempt_count == 2
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE sentinel_alert_outbox SET"
            " delivery_expires_at=clock_timestamp()-INTERVAL '1 second'"
            " WHERE alert_id=%s", (alert.alert_id,))
    conn.commit()

    recovered = outbox.claim_next(
        conn, holder_id="third", claim_seconds=30)
    assert recovered.state is AlertState.DELIVERING
    assert recovered.attempt_count == 3
    assert recovered.delivery_holder == "third"
    assert recovered.idempotency_key == alert.idempotency_key
    with conn.cursor() as cur:
        cur.execute(
            "SELECT action FROM sentinel_alert_delivery_events"
            " WHERE alert_id=%s ORDER BY seq", (alert.alert_id,))
        assert [row[0] for row in cur.fetchall()] == [
            "CLAIMED", "RETRY_SCHEDULED", "CLAIMED", "RETRY_SCHEDULED", "CLAIMED"]


def test_concurrent_claimers_receive_distinct_alerts(conn, pg) -> None:
    for key in ("concurrent-a", "concurrent-b"):
        outbox.enqueue(
            conn, idempotency_key=key, event_type="TEST", severity="INFO",
            payload={"key": key})
    start = threading.Barrier(2)

    def claim(holder):
        worker = feed_store.connect(pg.sync_dsn)
        try:
            start.wait(timeout=10)
            claimed = outbox.claim_next(
                worker, holder_id=holder, claim_seconds=30)
            assert claimed is not None
            return claimed.alert_id
        finally:
            worker.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        claimed = {
            future.result(timeout=30)
            for future in [
                pool.submit(claim, "alerter-a"),
                pool.submit(claim, "alerter-b"),
            ]
        }
    assert len(claimed) == 2


@pytest.mark.asyncio
async def test_dispatch_operates_while_fresh_automation_is_killed(conn) -> None:
    delivered = []

    class MemoryAdapter:
        async def deliver(self, alert, idempotency_key):
            delivered.append((alert.event_type, idempotency_key))

    alert = outbox.enqueue(
        conn, idempotency_key="disabled-alert", event_type="CERT_EXPIRED",
        severity="CRITICAL", payload={"certificate": "x"})

    result = await outbox.dispatch_once(
        conn, adapter=MemoryAdapter(), holder_id="alert-worker")

    assert result.delivered
    assert result.alert is not None
    assert result.alert.state is AlertState.DELIVERED
    assert delivered == [("CERT_EXPIRED", alert.idempotency_key)]


@pytest.mark.asyncio
async def test_dispatch_failure_is_committed_not_lost(conn) -> None:
    class BrokenAdapter:
        def deliver(self, alert, idempotency_key):
            raise TimeoutError("remote outcome unavailable")

    outbox.enqueue(
        conn, idempotency_key="one-shot", event_type="AUTOMATION_BLOCKED",
        severity="ERROR", payload={}, max_attempts=1)

    result = await outbox.dispatch_once(
        conn, adapter=BrokenAdapter(), holder_id="alert-worker")

    assert not result.dead_lettered
    assert result.alert.state is AlertState.PENDING
    assert "TimeoutError" in result.error


@pytest.mark.asyncio
async def test_terminal_transport_failure_dead_letters_without_retry(conn) -> None:
    class TerminalFailure(RuntimeError):
        retryable = False

    class RejectedAdapter:
        def deliver(self, alert, idempotency_key):
            raise TerminalFailure("webhook credentials rejected")

    outbox.enqueue(
        conn, idempotency_key="terminal-webhook", event_type="TEST",
        severity="CRITICAL", payload={}, max_attempts=8)

    result = await outbox.dispatch_once(
        conn, adapter=RejectedAdapter(), holder_id="alert-worker")

    assert result.dead_lettered
    assert result.alert is not None
    assert result.alert.attempt_count == 1
    assert "webhook credentials rejected" in result.error


def test_dispatcher_health_transitions_and_recovers_durably(conn) -> None:
    starting = alert_health.register(conn, dispatcher_id="primary")
    assert starting.state == alert_health.STARTING

    idle = alert_health.heartbeat(conn, dispatcher_id="primary")
    assert idle.state == alert_health.HEALTHY
    assert idle.last_success_at is None
    alert_health.require_healthy(
        conn, dispatcher_id="primary", maximum_age_seconds=30,
        startup_grace_seconds=300)

    healthy = alert_health.record_success(conn, dispatcher_id="primary")
    assert healthy.state == alert_health.HEALTHY
    assert healthy.consecutive_failures == 0

    degraded = alert_health.record_failure(
        conn, dispatcher_id="primary", error="timeout",
        maximum_failures=2)
    assert degraded.state == alert_health.DEGRADED
    failed = alert_health.record_failure(
        conn, dispatcher_id="primary", error="timeout again",
        maximum_failures=2)
    assert failed.state == alert_health.FAILED

    recovered = alert_health.record_success(conn, dispatcher_id="primary")
    assert recovered.state == alert_health.HEALTHY
    assert recovered.consecutive_failures == 0
    assert recovered.last_error is None


def test_dispatcher_health_fails_on_stale_heartbeat_and_dead_letter(conn) -> None:
    alert_health.register(conn, dispatcher_id="primary")
    alert_health.record_success(conn, dispatcher_id="primary")
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE sentinel_alert_dispatcher_health SET"
            " heartbeat_at=clock_timestamp()-INTERVAL '2 minutes'"
            " WHERE dispatcher_id='primary'")
    conn.commit()
    with pytest.raises(alert_health.AlertDispatcherUnhealthy, match="stale"):
        alert_health.require_healthy(
            conn, dispatcher_id="primary", maximum_age_seconds=30,
            startup_grace_seconds=300)

    alert_health.record_success(conn, dispatcher_id="primary")
    outbox.enqueue(
        conn, idempotency_key="dead-letter-health", event_type="TEST",
        severity="CRITICAL", payload={}, max_attempts=1)
    claimed = outbox.claim_next(
        conn, holder_id="alert-worker", claim_seconds=30)
    assert claimed is not None
    outbox.mark_failed(
        conn, alert_id=claimed.alert_id, holder_id="alert-worker",
        attempt=claimed.attempt_count,
        error="terminal", retryable=False)
    with pytest.raises(alert_health.AlertDispatcherUnhealthy,
                       match="dead-letter"):
        alert_health.require_healthy(
            conn, dispatcher_id="primary", maximum_age_seconds=30,
            startup_grace_seconds=300)
