"""Native late lease evidence, original clocks and transactional publication."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import inspect
from queue import Queue
from threading import Event, Thread
import time
from types import SimpleNamespace
import uuid

import psycopg
import pytest

from sentinel.panel import model, operational_snapshot as snapshots
from sentinel.panel import projection_service as producer, review_schema, review_store, sources
from tests.sentinel.test_operational_read_projection import install_projection
from tests.sentinel.test_supervisor_dependency_bounds import conn, pg  # noqa: F401
from tests.support.panel_composition import compose_and_publish, isolate_storage


def database_now(conn):
    return conn.execute('SELECT clock_timestamp()').fetchone()[0]


def renew_native(conn, *, seconds=12):
    """Write qualification evidence with the real service's 12s/3s clocks."""
    heartbeat = database_now(conn)
    expiry, wake = heartbeat+timedelta(seconds=seconds), heartbeat+timedelta(seconds=3)
    conn.execute("UPDATE sentinel_automation_lease SET holder_id='late-holder',"
        "fence_token=11,control_generation=7,acquired_at=%s,heartbeat_at=%s,expires_at=%s WHERE id=1",
        (heartbeat-timedelta(seconds=3), heartbeat, expiry))
    conn.execute("INSERT INTO sentinel_automation_service_instances"
        "(instance_id,state,heartbeat_at,next_wake_at) VALUES('late-holder','WAITING',%s,%s) "
        "ON CONFLICT(instance_id) DO UPDATE SET state=EXCLUDED.state,"
        "heartbeat_at=EXCLUDED.heartbeat_at,next_wake_at=EXCLUDED.next_wake_at,last_error=NULL",
        (heartbeat, wake))
    conn.commit()
    return heartbeat, expiry, wake


def composed_rows(now):
    old_heartbeat, old_expiry = now-timedelta(seconds=9), now+timedelta(seconds=3)
    recovery = model.RecoveryEvidence(phase='AUTOMATION_DISCOVERY', automatic=True,
        next_attempt_at=old_heartbeat+timedelta(seconds=3), deadline=old_expiry)
    leader = model.automation_leader_row(installed=True, enabled=True, killed=False,
        holder='late-holder', fence=11, heartbeat_at=old_heartbeat,
        expires_at=old_expiry, active=True)
    cycle = model.automation_cycle_row(installed=True, enabled=True,
        discovery_recovery=recovery)
    # This independent source clock must survive the late lease replacement.
    book = model.Row('book', 'Book', 'VERIFIED', model.OK,
        as_of=now-timedelta(seconds=100), freshness=timedelta(seconds=600), required_current=True)
    ordinary = [model.Row(key, key, 'CURRENT', model.OK, as_of=now,
        freshness=timedelta(seconds=45), required_current=True) for key in (
            'runtime_identity', 'automation', 'authority', 'feed', 'broker',
            'alpaca_account', 'backup_restore', 'automation_alerts', 'alert_dispatcher')]
    return [*ordinary, leader, cycle, *model.automation_step_rows(
        installed=True, enabled=True, discovery_recovery=recovery), book]


@pytest.fixture
def late(conn, monkeypatch, tmp_path):
    isolate_storage(tmp_path, monkeypatch)
    monkeypatch.setattr(producer, 'HEARTBEAT', tmp_path/'operational-heartbeat')
    monkeypatch.setenv('SENTINEL_PUBLICATION_RECEIPT_KEY', 'late-qualification-'+'x'*40)
    monkeypatch.setenv('SENTINEL_REVIEWED_DEPLOYMENT_MODE', 'shadow')
    monkeypatch.setenv('ALPACA_BASE_URL', 'https://paper-api.alpaca.markets')
    install_projection(conn)
    conn.execute("INSERT INTO sentinel_account_binding"
        "(id,deployment_id,broker,broker_account_id,ownership_state) "
        "VALUES(1,'private-late','alpaca','paper-qualified','SENTINEL_OWNED')")
    conn.commit()
    review_schema.install_quiescent(conn)
    conn.execute("UPDATE sentinel_automation_control SET enabled=TRUE,kill_switch_engaged=FALSE,"
        "generation=7,deployment_id='private-late',broker='alpaca',broker_account_id='paper-qualified',"
        "takeover_epoch=1,certificate_sha256=%s,rollout_mode='PAPER_OBSERVATION_ONLY',"
        "rollout_version=1,config_sha256=%s WHERE id=1", ('a'*64, 'b'*64))
    conn.commit()
    owner_id = str(uuid.uuid4())
    conn.execute(f'INSERT INTO {snapshots.schema.OWNER} VALUES '
        "(1,%s,clock_timestamp()+interval '600 seconds')", (owner_id,))
    conn.commit()
    heartbeat, expiry, wake = renew_native(conn)
    rows = composed_rows(heartbeat)
    page = model.Panel(rows=rows, now=heartbeat, local_paper_mode=True)
    monkeypatch.setattr(sources, 'build_panel', lambda **_: page)
    from sentinel.panel import composition
    monkeypatch.setattr(composition, 'native_services', lambda _conn, rows, **_: rows)
    return SimpleNamespace(conn=conn, owner_id=owner_id, heartbeat=heartbeat,
        expiry=expiry, wake=wake, rows=rows, page=page)


def by_key(rows, key):
    return next(row for row in rows if row.key == key)


def publish(late):
    return compose_and_publish(late.conn.info.dsn, late.owner_id,
        '/var/lib/sentinel', 'late-qualification-verifier')


def stored(conn):
    receipt = conn.execute(f'SELECT observed_at,valid_until,envelope,signature '
        f'FROM {snapshots.schema.RECEIPTS} WHERE scope=%s', ('DASHBOARD',)).fetchone()
    state = conn.execute('SELECT payload,signature FROM sentinel_dashboard_review_state').fetchall()
    events = conn.execute('SELECT sequence,payload,signature FROM sentinel_dashboard_review_events '
                         'ORDER BY sequence').fetchall()
    conn.rollback()
    return receipt, state, events


class CountedConnection:
    def __init__(self, connection):
        self.connection = connection
        self.statements = []

    def execute(self, statement, *args):
        self.statements.append(statement)
        return self.connection.execute(statement, *args)


def assert_native_clocks(late, rows):
    leader = by_key(rows, 'automation_leader')
    assert leader.status == model.OK
    assert leader.as_of == late.heartbeat and leader.valid_until == late.expiry
    assert leader.freshness == timedelta(seconds=30)
    for key in ('automation_cycle', 'automation_step_discovery'):
        row = by_key(rows, key)
        assert row.operational_fact.state == 'DISCOVERY_WAIT'
        assert row.recovery.phase == 'AUTOMATION_DISCOVERY'
        assert row.recovery.deadline == late.expiry
        assert row.recovery.next_attempt_at == late.wake
    assert by_key(rows, 'book') is by_key(late.rows, 'book')


def test_one_native_statement_refreshes_all_shared_discovery_boundaries(late):
    connection = CountedConnection(late.conn)
    refreshed = sources._late_automation_rows(connection, late.rows)
    assert len(connection.statements) == 1
    assert_native_clocks(late, refreshed)
    assert by_key(late.rows, 'automation_leader').valid_until < late.expiry
    assert by_key(late.rows, 'automation_cycle').recovery.deadline < late.expiry


def test_real_publication_uses_new_lease_and_keeps_independent_evidence_clock(late):
    result = publish(late)
    assert datetime.fromisoformat(result['valid_until']) == late.expiry
    receipt, _, _ = stored(late.conn)
    assert receipt[1] == late.expiry
    encoded = receipt[2]['panel']['rows']
    assert datetime.fromisoformat(by_key_dict(encoded, 'automation_leader')['as_of']) == late.heartbeat
    assert datetime.fromisoformat(by_key_dict(encoded, 'automation_cycle')['recovery']['deadline']) == late.expiry
    assert datetime.fromisoformat(by_key_dict(encoded, 'automation_step_discovery')['recovery']['deadline']) == late.expiry
    assert datetime.fromisoformat(by_key_dict(encoded, 'book')['as_of']) == by_key(late.rows, 'book').as_of


def by_key_dict(rows, key):
    return next(row for row in rows if row['key'] == key)


@pytest.mark.parametrize('defect', ['wrong_generation', 'killed', 'missing_holder',
    'missing_instance', 'stale_instance', 'foreign_instance', 'instance_error', 'expired_lease'])
def test_late_negative_evidence_cannot_retain_previous_positive_wait(late, defect):
    conn = late.conn
    if defect == 'wrong_generation':
        conn.execute('UPDATE sentinel_automation_lease SET control_generation=8 WHERE id=1')
    elif defect == 'killed':
        conn.execute('UPDATE sentinel_automation_control SET kill_switch_engaged=TRUE WHERE id=1')
    elif defect == 'missing_holder':
        conn.execute('UPDATE sentinel_automation_lease SET holder_id=NULL,control_generation=NULL,'
            'acquired_at=NULL,heartbeat_at=NULL,expires_at=NULL WHERE id=1')
    elif defect == 'missing_instance':
        conn.execute("DELETE FROM sentinel_automation_service_instances WHERE instance_id='late-holder'")
    elif defect == 'stale_instance':
        conn.execute("UPDATE sentinel_automation_service_instances SET heartbeat_at=clock_timestamp()-"
            "interval '31 seconds' WHERE instance_id='late-holder'")
    elif defect == 'foreign_instance':
        conn.execute("UPDATE sentinel_automation_lease SET holder_id='unregistered-holder' WHERE id=1")
    elif defect == 'instance_error':
        conn.execute("UPDATE sentinel_automation_service_instances SET last_error='qualification refusal' "
                     "WHERE instance_id='late-holder'")
    else:
        conn.execute("UPDATE sentinel_automation_lease SET heartbeat_at=clock_timestamp()-interval '13 seconds',"
            "expires_at=clock_timestamp()-interval '1 second' WHERE id=1")
    conn.commit()
    refreshed = sources._late_automation_rows(conn, late.rows)
    for key in ('automation_cycle', 'automation_step_discovery'):
        assert by_key(refreshed, key).recovery is None
    if defect in {'wrong_generation', 'killed', 'missing_holder', 'expired_lease'}:
        assert by_key(refreshed, 'automation_leader').status != model.OK
    if defect == 'instance_error':
        assert by_key(refreshed, 'automation_cycle').status == model.FAIL


def insert_cycle(conn, *, generation):
    now = database_now(conn)
    cycle_id = 'late-cycle-'+str(generation)
    conn.execute("INSERT INTO sentinel_automation_cycles"
        "(cycle_id,state,decision_session,effective_session,deployment_id,broker,broker_account_id,"
        "takeover_epoch,control_generation,certificate_sha256,rollout_mode,rollout_version,config_sha256,"
        "decision_close_at,prepare_at,execution_open_at,execute_at,execution_close_at) "
        "VALUES(%s,'DISCOVERED',%s,%s,'private-late','alpaca','paper-qualified',1,%s,%s,"
        "'PAPER_OBSERVATION_ONLY',1,%s,%s,%s,%s,%s,%s)",
        (cycle_id, now.date(), (now+timedelta(days=1)).date(), generation, 'a'*64, 'b'*64,
         now-timedelta(hours=2), now-timedelta(hours=1), now, now, now+timedelta(hours=1)))
    conn.commit()
    return cycle_id


@pytest.mark.parametrize('via_event', [False, True])
def test_current_generation_cycle_presence_refuses_old_discovery_absence(late, via_event):
    cycle_id = insert_cycle(late.conn, generation=6 if via_event else 7)
    if via_event:
        late.conn.execute("INSERT INTO sentinel_automation_cycle_events"
            "(cycle_id,to_state,control_generation,fence_token) VALUES(%s,'DISCOVERED',7,11)", (cycle_id,))
        late.conn.commit()
    with pytest.raises(ValueError, match='cycle changed'):
        sources._late_automation_rows(late.conn, late.rows)


def test_an_unrelated_generation_does_not_invent_a_current_cycle(late):
    insert_cycle(late.conn, generation=6)
    assert_native_clocks(late, sources._late_automation_rows(late.conn, late.rows))


def test_real_native_future_heartbeat_is_not_replaced_by_observation_time(late):
    future = database_now(late.conn)+timedelta(seconds=60)
    late.conn.execute('UPDATE sentinel_automation_lease SET heartbeat_at=%s,expires_at=%s WHERE id=1',
                      (future, future+timedelta(seconds=12)))
    late.conn.commit()
    rows = sources._late_automation_rows(late.conn, late.rows)
    leader = by_key(rows, 'automation_leader')
    assert leader.as_of == future and leader.valid_until == future+timedelta(seconds=12)
    assert leader.effective_status(database_now(late.conn)) == model.FAIL


def test_unrepresentable_native_expiry_refuses_instead_of_copying_old_positive(late):
    late.conn.execute("UPDATE sentinel_automation_lease SET expires_at='infinity' WHERE id=1")
    late.conn.commit()
    with pytest.raises((ValueError, psycopg.DataError)):
        sources._late_automation_rows(late.conn, late.rows)


def test_unreadable_late_query_cannot_publish_or_renew_previous_positive(late):
    publish(late)
    before = stored(late.conn)
    late.conn.execute('LOCK TABLE sentinel_automation_service_instances IN ACCESS EXCLUSIVE MODE')
    try:
        with pytest.raises(psycopg.errors.LockNotAvailable):
            publish(late)
    finally:
        late.conn.rollback()
    assert stored(late.conn) == before


def test_real_collector_late_refusal_publishes_negative_instead_of_old_positive(late):
    publish(late)
    before = stored(late.conn)
    late.conn.execute('LOCK TABLE sentinel_automation_service_instances IN ACCESS EXCLUSIVE MODE')
    try:
        result = producer.collect_result(late.conn.info.dsn, late.owner_id,
            '/var/lib/sentinel', 'late-qualification-verifier')
    finally:
        late.conn.rollback()
    assert result['outcome'] == 'PUBLISHED'
    receipt, states, _ = stored(late.conn)
    assert receipt[3] != before[0][3]
    rows = receipt[2]['panel']['rows']
    assert [row['key'] for row in rows] == ['operational_projection']
    assert rows[0]['status'] == model.UNKNOWN
    assert receipt[2]['panel']['trial_details']['operational_failure']['code'] == 'READ_LOCK_UNAVAILABLE'
    assert states[0][0]['head'] > before[1][0][0]['head']


def test_actual_expiry_after_late_observation_rolls_back_snapshot_and_review(late, monkeypatch):
    from sentinel.panel import serialization
    publish(late)
    before = stored(late.conn)
    heartbeat = database_now(late.conn)
    expiry = heartbeat+timedelta(seconds=1)
    late.conn.execute('UPDATE sentinel_automation_lease SET heartbeat_at=%s,expires_at=%s WHERE id=1',
                      (heartbeat, expiry))
    late.conn.execute("UPDATE sentinel_automation_service_instances SET heartbeat_at=%s,next_wake_at=%s "
                      "WHERE instance_id='late-holder'", (heartbeat, heartbeat+timedelta(milliseconds=100)))
    late.conn.commit()
    original = serialization.preflight
    def expire_during_real_publication(panel):
        if panel.operator_review is None:
            return original(panel)
        assert panel.row('automation_leader').valid_until == expiry
        assert database_now(late.conn) < expiry
        # The database clock, not a mocked datetime or widened expiry, advances.
        late.conn.execute('SELECT pg_sleep(1.05)')
        late.conn.rollback()
        original(panel)
    monkeypatch.setattr(serialization, 'preflight', expire_during_real_publication)
    with pytest.raises(producer.CollectionSuperseded, match='expired before commit'):
        publish(late)
    assert stored(late.conn) == before


def test_removed_late_observation_has_an_executed_publication_falsifier(late, monkeypatch):
    source = inspect.getsource(producer.publish_once)
    guard = 'panel = replace(panel, rows=sources._late_automation_rows(conn, panel.rows))'
    assert source.count(guard) == 1
    namespace = {}
    exec(compile(source.replace(guard, 'panel = panel'), '<removed-late-native-observation>', 'exec'),
         vars(producer), namespace)
    monkeypatch.setattr(producer, 'publish_once', namespace['publish_once'])
    with pytest.raises(AssertionError):
        test_real_publication_uses_new_lease_and_keeps_independent_evidence_clock(late)


def test_three_real_publications_overlap_independent_native_heartbeat_renewal(
        late, monkeypatch, record_property):
    """Actual concurrent SQL renewals during controlled source delays; no HTTP."""
    stopped, started = Event(), Event()
    failures, renewals = Queue(), Queue()
    source_windows, publications = [], []
    original_rows = tuple(late.rows)
    original_clocks = tuple((row.as_of, row.valid_until, row.freshness, row.recovery)
                            for row in original_rows)

    def heartbeat_writer():
        try:
            with psycopg.connect(late.conn.info.dsn, connect_timeout=3,
                    options='-c statement_timeout=3000 -c lock_timeout=1000') as writer:
                while not stopped.is_set():
                    renewals.put(renew_native(writer))
                    started.set()
                    if stopped.wait(3):
                        break
        except BaseException as error:
            failures.put(error)
            started.set()

    def controlled_collection(**_):
        cost = (1, 4, 2)[len(source_windows)]
        beginning = database_now(late.conn)
        late.conn.rollback()
        source_windows.append([beginning, None, cost])
        time.sleep(cost)
        source_windows[-1][1] = database_now(late.conn)
        late.conn.rollback()
        # Preserve the original composed rows, including independent proof clocks.
        # Only the producer's real late native query may replace leader evidence.
        return late.page

    monkeypatch.setattr(sources, 'build_panel', controlled_collection)
    thread = Thread(target=heartbeat_writer, name='private-native-lease-renewal', daemon=True)
    thread.start()
    try:
        assert started.wait(10), 'private heartbeat writer did not start'
        if not failures.empty():
            raise failures.get_nowait()
        for _ in range(3):
            publish(late)
            receipt, _, _ = stored(late.conn)
            rows = receipt[2]['panel']['rows']
            leader = by_key_dict(rows, 'automation_leader')
            heartbeat = datetime.fromisoformat(leader['as_of'])
            expiry = datetime.fromisoformat(leader['valid_until'])
            assert leader['status'] == model.OK
            assert expiry-heartbeat == timedelta(seconds=12)
            assert receipt[1] == expiry and receipt[0] < expiry
            for key in ('automation_cycle', 'automation_step_discovery'):
                row = by_key_dict(rows, key)
                assert row['operational_fact']['state'] == 'DISCOVERY_WAIT'
                assert datetime.fromisoformat(row['recovery']['deadline']) == expiry
            if publications:
                assert receipt[0] < publications[-1]['expiry']
            assert datetime.fromisoformat(by_key_dict(rows, 'book')['as_of']) == by_key(
                original_rows, 'book').as_of
            assert tuple(late.rows) == original_rows
            assert tuple((row.as_of, row.valid_until, row.freshness, row.recovery)
                         for row in late.rows) == original_clocks
            publications.append(dict(generated_at=receipt[0], heartbeat=heartbeat, expiry=expiry))
            if not failures.empty():
                raise failures.get_nowait()
    finally:
        stopped.set()
        thread.join(15)
        assert not thread.is_alive(), 'private heartbeat writer did not finish bounded cleanup'
    if not failures.empty():
        raise failures.get_nowait()
    committed = []
    while not renewals.empty():
        committed.append(renewals.get_nowait())
    assert len(publications) == 3 and len(source_windows) == 3
    assert all((item['heartbeat'], item['expiry']) in {(hb, expiry) for hb, expiry, _ in committed}
               for item in publications)
    beginning, ending, _ = source_windows[1]
    assert any(beginning < heartbeat < ending for heartbeat, _, _ in committed), (
        'no native heartbeat committed during the four-second collection')
    record_property('private_concurrent_lease_publications', [
        {key: value.isoformat() for key, value in item.items()} for item in publications])
