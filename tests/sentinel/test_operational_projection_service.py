"""Actual PostgreSQL operational ownership, review/snapshot atomicity and ACK."""
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
import inspect
from threading import Event
import time
from types import SimpleNamespace
import uuid

import psycopg
import pytest

from sentinel.panel import model, operational_snapshot as snapshots, projection_service as producer
from sentinel.panel import review, review_schema, review_store
from tests.sentinel.test_operational_read_projection import install_projection
from tests.sentinel.test_supervisor_dependency_bounds import conn, pg  # noqa: F401
from tests.support.panel_composition import compose_and_publish, isolate_storage


@pytest.fixture
def operational(conn, monkeypatch, tmp_path):
    isolate_storage(tmp_path, monkeypatch)
    monkeypatch.setenv('SENTINEL_PUBLICATION_RECEIPT_KEY', 'private-qualification-'+'x'*40)
    monkeypatch.setenv('SENTINEL_REVIEWED_DEPLOYMENT_MODE', 'shadow')
    monkeypatch.setenv('ALPACA_BASE_URL', 'https://paper-api.alpaca.markets')
    install_projection(conn)
    conn.execute("INSERT INTO sentinel_account_binding(id,deployment_id,broker,broker_account_id,ownership_state) "
        "VALUES(1,'private','alpaca','paper-qualified','SENTINEL_OWNED') ON CONFLICT(id) DO UPDATE SET "
        "deployment_id=EXCLUDED.deployment_id,broker=EXCLUDED.broker,broker_account_id=EXCLUDED.broker_account_id,"
        "ownership_state=EXCLUDED.ownership_state")
    conn.commit()
    review_schema.install_quiescent(conn)
    owner_id = str(uuid.uuid4())
    conn.execute(f'INSERT INTO {snapshots.schema.OWNER} VALUES '
        "(1,%s,clock_timestamp()+interval '600 seconds')", (owner_id,))
    conn.commit()
    condition = {'broker': model.OK, 'collect': None, 'financial': False, 'rich': False}
    from sentinel.panel import composition, sources
    def collect(**_):
        now = datetime.now(timezone.utc)
        keys = ('runtime_identity', 'automation', 'automation_leader', 'authority', 'feed',
                'broker', 'alpaca_account', 'backup_restore', 'automation_alerts', 'alert_dispatcher')
        page = model.Panel(now=now, local_paper_mode=True,
            rows=[model.Row(key, key, 'CURRENT', condition.get(key, model.OK),
                    as_of=now, freshness=timedelta(seconds=45), required_current=True) for key in keys])
        if condition['financial']:
            page = replace(page, rows=[*page.rows, *financial_rows('SHADOW', now),
                                     *financial_rows('PAPER', now)])
        if condition['rich']:
            from tests.sentinel.test_operational_dashboard_snapshot import panel as rich_panel
            combined = {row.key: row for row in [*page.rows, *rich_panel(now).rows]}
            page = replace(page, rows=list(combined.values()))
        if condition['collect'] is not None:
            condition['collect']()
        return page
    monkeypatch.setattr(sources, 'build_panel', collect)
    # Native late-lease behavior has separate real-PostgreSQL qualification.
    monkeypatch.setattr(sources, '_late_automation_rows', lambda _conn, rows: rows)
    monkeypatch.setattr(composition, 'native_services', lambda _conn, rows, **_: rows)
    monkeypatch.setattr(sources, '_shadow_worker_row', lambda *_, **__: None)
    return conn, owner_id, condition


def publish(operational, *, instance='one-verifier', prior_failed=False):
    conn, owner_id, _ = operational
    return compose_and_publish(conn.info.dsn, owner_id, '/var/lib/sentinel', instance, prior_failed)


def state(conn):
    key = review_store.scope(conn)
    row = conn.execute('SELECT payload,signature FROM sentinel_dashboard_review_state WHERE scope_sha256=%s',
                       (key,)).fetchone()
    if row is None:
        conn.rollback()
        return None
    review_store.authenticate(dict(scope=key, state=row[0]), row[1], purpose=review_store.SCHEMA)
    conn.rollback()
    return row[0]


@pytest.mark.parametrize('case', ['fee_wait', 'current_mismatch', 'removed_fee_attribution'])
def test_owned_paper_observer_records_only_actual_failure_during_fee_wait(
        operational, monkeypatch, case):
    from sentinel import activation_fee_wait, informational_paper_mirror as mirror
    from sentinel.panel import attempt_store, authority_reader, observer_codec, read_projection
    from sentinel.panel import sources, verification_service as verifier

    conn, owner, _ = operational
    decision = date(2026, 11, 16)
    observed = review_store.database_now(conn)
    cutoff = observed + timedelta(seconds=120)
    conn.rollback()
    witness = activation_fee_wait.ActivationFeeWait(
        decision, observed, cutoff, cutoff, 'd'*64, 200)
    monkeypatch.setattr(activation_fee_wait, 'read_owned',
                        lambda _conn, *, now, **_: witness if observed <= now < cutoff else None)
    cycle = dict(state='WAITING_OPEN', decision_session=decision.isoformat(),
                 plan_id='paper-fixture', plan_fingerprint='a'*64)
    monkeypatch.setattr(sources, '_latest_automation_cycle', lambda _: cycle)
    monkeypatch.setattr(sources, '_informational_mirror_count', lambda _: 1)
    for name in ('_scheduled_preopen_mirror', '_in_progress_paper_mirror', '_completed_postopen_mirror'):
        monkeypatch.setattr(sources, name, lambda *_: None)
    monkeypatch.setattr(mirror, 'require_transport_permitted', lambda *_a, **_kw: {
        'status': mirror.MISMATCH, 'historical_mismatch_count': 1})

    def current_plan_status(*_a, **_kw):
        if case == 'current_mismatch':
            raise mirror.InformationalPaperMirrorMismatch('current plan share-unit mismatch')
        return {'status': mirror.PENDING}
    monkeypatch.setattr(mirror, 'require_current_plan_status', current_plan_status)
    if case == 'removed_fee_attribution':
        source = inspect.getsource(sources._scheduled_paper_mirror)
        guard = 'wait is not None and wait.decision_session.isoformat() == frontier'
        assert source.count(guard) == 1
        namespace = {}
        exec(compile(source.replace(guard, 'False and '+guard), '<removed fee attribution>', 'exec'),
             vars(sources), namespace)
        monkeypatch.setattr(sources, '_scheduled_paper_mirror', namespace['_scheduled_paper_mirror'])

    publication = SimpleNamespace(current=lambda _: SimpleNamespace(version=22),
                                  frontier=lambda *_: decision.isoformat())

    def observe(database_url, include_paper, _subject):
        assert include_paper
        with psycopg.connect(database_url) as read:
            read.execute('SET TRANSACTION READ ONLY')
            paper = sources._dual_paper_row(read, informational_paper_mirror=mirror,
                                           publication=publication, feed_store=None)
            return observer_codec.pack([paper], [], observed_at=review_store.database_now(read))

    reader = authority_reader.Reader(expected_keys=frozenset({'paper_reconciliation'}),
        unknown_factory=verifier.paper_unknown, retain_failed_attempt=True, observer=observe,
        runner=lambda run, *args, **_: run(*args))
    previous, stopped = {}, Event()
    deadline = time.monotonic() + 15
    dsn = conn.info.dsn
    verifier._refresh_readers(conn, {'PAPER': reader}, dsn, owner, previous, stopped, deadline)
    pending = reader.pending
    if pending is not None:
        pending.join(timeout=5)
        assert not pending.is_alive()
    verifier._refresh_readers(conn, {'PAPER': reader}, dsn, owner, previous, stopped, deadline)

    now = review_store.database_now(conn)
    history = attempt_store.read_owned(conn, scope='PAPER', now=now)
    assert history is not None and history['financial_authority'] is False
    key = review_store.scope(conn)
    notes = [event for event in review_store.recent(conn, key)
             if event['details'].get('verification_scope') == 'PAPER']
    rows, _, _, errors = read_projection.read_owned(conn, dsn, only_scope='PAPER', now=now)
    assert not errors and len(rows) == 1
    if case != 'fee_wait':
        assert rows[0].status == model.FAIL
        assert ('current plan share-unit mismatch' if case == 'current_mismatch'
                else 'historical informational mirror mismatch(es) remain recorded') in rows[0].detail
        assert history['latest']['outcome'] == 'FAILED'
        assert len(history['failures']) == len(notes) == 1
        assert notes[0]['kind'] == 'REVIEW'
        assert notes[0]['details']['attempt'] == history['failures'][0]['first']
        assert notes[0]['details']['attempt']['diagnostic']['code'] == 'NEGATIVE_RESULT'
    else:
        assert rows[0].status == model.PENDING and rows[0].required_current
        assert rows[0].operational_fact.state == 'HISTORICAL_READINESS_WITHDRAWN'
        assert rows[0].operational_fact.session == decision
        assert rows[0].as_of == observed and rows[0].valid_until == cutoff
        assert history['latest']['outcome'] != 'FAILED'
        assert not history['failures'] and not notes
        assert conn.execute(f'SELECT valid_until FROM {snapshots.schema.RECEIPTS} '
                            "WHERE scope='PAPER'").fetchone() == (cutoff,)
        expired, _, _, _ = read_projection.read_owned(conn, dsn, only_scope='PAPER', now=cutoff)
        assert expired[0].effective_status(cutoff) in {model.FAIL, model.UNKNOWN}
        assert expired[0].operational_fact is None


def test_split_composition_reuses_heavy_rows_with_native_publication_and_subject_fence(operational,monkeypatch,tmp_path):
    from sentinel.panel import composition, sources
    conn,owner,condition=operational
    instance=str(uuid.uuid4())
    monkeypatch.setattr(composition.tempfile,'gettempdir',lambda:str(tmp_path))
    native=[]
    monkeypatch.setattr(composition,'native_services',lambda c,rows,**kw:(native.append(True) or rows))
    heavy=[]
    condition['collect']=lambda:heavy.append(True)
    result=composition.collect(conn.info.dsn,owner,'/private',instance)
    original,_,_,expiry=composition.read(owner,instance,now=datetime.now(timezone.utc))
    for _ in range(3):
        producer.publish_once(conn.info.dsn,owner,'/private',instance)
        page=producer.read(conn.info.dsn)
        assert page.row('broker').as_of==original.row('broker').as_of
        assert datetime.fromisoformat(result['valid_until'])==expiry
    assert heavy==[True] and len(native)==3
    original_context=snapshots.context
    monkeypatch.setattr(snapshots,'context',lambda *args:'0'*64)
    with pytest.raises(producer.CollectionSuperseded,match='inputs changed'):
        producer.publish_once(conn.info.dsn,owner,'/private',instance)
    monkeypatch.setattr(snapshots,'context',original_context)
    composition.failure(owner,instance,TimeoutError())
    result=producer.collect_result(conn.info.dsn,owner,'/private',instance)
    assert result['outcome']=='PUBLISHED'
    assert producer.read(conn.info.dsn).row('operational_projection').status==model.UNKNOWN


def test_rendered_review_action_acknowledges_exact_published_view(operational, monkeypatch):
    from html import unescape
    import re

    from fastapi.testclient import TestClient
    from sentinel.panel.app import app

    conn, _, condition = operational
    origin = 'https://private.invalid'
    monkeypatch.setenv('SENTINEL_DATABASE_URL', conn.info.dsn)
    monkeypatch.setenv('SENTINEL_PUBLIC_ORIGIN', origin)

    def current_button(client):
        document = client.get('/?document=1')
        assert document.status_code == 200
        assert document.headers['X-Sentinel-Panel-Status'] == 'CURRENT'
        return re.search(r'<button id="review-acknowledge"[^>]+data-view-token="([^"]+)"', document.text)

    def click(client, button):
        assert button is not None
        return client.post('/review/acknowledge', headers={'Origin': origin},
                           json={'token': unescape(button.group(1))})

    with TestClient(app, base_url=origin) as client:
        publish(operational)
        original = current_button(client)
        condition['broker'] = model.FAIL
        publish(operational)
        assert click(client, original).status_code == 409
        assert current_button(client) is None
        condition['broker'] = model.OK
        publish(operational)
        response = click(client, current_button(client))
        assert response.status_code == 200
        accepted = response.json()
        assert accepted['status'] == 'CLEAN' and accepted['reviewed_head'] == accepted['head']
        publish(operational)
        assert current_button(client) is None
        page = client.get('/panel.json').json()
        assert page['operator_review']['status'] == 'CLEAN'
        assert page['dashboard_health']['color'] == 'green'


def test_background_failure_and_recovery_record_once_without_any_http(operational):
    conn, _, condition = operational
    publish(operational)
    baseline = producer.read(conn.info.dsn)
    assert baseline.operator_review.status == 'REVIEW' and baseline.operator_review.token
    clean = review.Recorder().acknowledge(baseline, conn.info.dsn, baseline.operator_review.token,
        actor='private qualifier', snapshot_guard=lambda c, p: producer.guard_acknowledgement(c, p, conn.info.dsn))
    assert clean.status == 'CLEAN'
    publish(operational)
    assert producer.read(conn.info.dsn).operator_review.status == 'CLEAN'
    condition['broker'] = model.FAIL
    publish(operational)
    failed = state(conn)
    assert failed['active'] == ['broker'] and failed['head'] > clean.head
    publish(operational)
    assert state(conn)['head'] == failed['head']
    condition['broker'] = model.OK
    publish(operational)
    recovered = producer.read(conn.info.dsn)
    assert recovered.operator_review.status == 'REVIEW'
    assert recovered.operator_review.reviewed_head == clean.head
    head = recovered.operator_review.head
    publish(operational)
    assert producer.read(conn.info.dsn).operator_review.head == head


@pytest.mark.parametrize('replace_owner', [False, True])
def test_slow_close_handoff_allows_owner_renewal_and_discards_changed_snapshot(
        operational, monkeypatch, replace_owner):
    from sentinel.panel import readiness_handoff

    conn, owner, _ = operational
    instance = 'slow-close-qualifier'
    publish(operational, instance=instance)
    before = state(conn)
    old = conn.execute(f'SELECT signature FROM {snapshots.schema.RECEIPTS} '
                       "WHERE scope='DASHBOARD'").fetchone()
    conn.rollback()
    replacement = str(uuid.uuid4()) if replace_owner else owner
    renewed = []

    def concurrent_renewal(*_args, **_kwargs):
        conn.execute("SET LOCAL lock_timeout='250ms'")
        saved = conn.execute(f'UPDATE {snapshots.schema.OWNER} '
            "SET owner_id=%s, expires_at=clock_timestamp()+interval '610 seconds' "
            'WHERE id=1 AND owner_id=%s RETURNING owner_id::text', (replacement, owner)).fetchone()
        conn.commit()
        renewed.append(saved)

    with monkeypatch.context() as race:
        race.setattr(readiness_handoff, 'capture', concurrent_renewal)
        result = producer.collect_result(conn.info.dsn, owner, '/private', instance)
    assert renewed == [(replacement,)], 'fast collector blocked the verifier owner heartbeat'
    assert result == {'outcome': 'SUPERSEDED'}
    assert state(conn) == before
    assert conn.execute(f'SELECT signature FROM {snapshots.schema.RECEIPTS} '
                        "WHERE scope='DASHBOARD'").fetchone() == old
    conn.rollback()
    if not replace_owner:
        assert producer.collect_result(conn.info.dsn, owner, '/private', instance)['outcome'] == 'PUBLISHED'


def test_negative_receipt_committed_during_close_handoff_supersedes_old_view(
        operational, monkeypatch):
    from sentinel.panel import readiness_handoff

    conn, owner, condition = operational
    condition['financial'] = True
    save_financial(conn, 'SHADOW')
    save_financial(conn, 'PAPER')
    instance = 'receipt-close-qualifier'
    publish(operational, instance=instance)
    before = state(conn)

    def negative_receipt(*_args, **_kwargs):
        conn.execute("SET LOCAL lock_timeout='250ms'")
        save_financial(conn, 'PAPER', [model.paper_reconciliation_row(state='MISMATCH')])

    monkeypatch.setattr(readiness_handoff, 'capture', negative_receipt)
    result = producer.collect_result(conn.info.dsn, owner, '/private', instance)
    assert result == {'outcome': 'SUPERSEDED'}
    assert state(conn) == before
    assert producer.read(conn.info.dsn).row('paper_reconciliation').status == model.FAIL


@pytest.mark.parametrize(('scope', 'existing'), [('SHADOW', True), ('SHADOW', False), ('PAPER', False)])
def test_attempt_committed_during_close_handoff_cannot_publish_old_progress(
        operational, monkeypatch, scope, existing):
    from sentinel.panel import attempt_store, readiness_handoff
    from tests.sentinel.test_observer_attempt_store import attempt

    conn, owner, _ = operational
    observed = datetime.now(timezone.utc) - timedelta(seconds=5)

    def save_attempt(index):
        conn.execute("SET LOCAL lock_timeout='250ms'")
        value = attempt(index=index, outcome='RUNNING', at=observed)
        value['completed_at'] = None
        attempt_store.publish_owned(conn, owner_id=owner, scope=scope, attempt=value,
                                    now=review_store.database_now(conn))
        conn.commit()

    def owner_version():
        return conn.execute(f'SELECT owner_id,expires_at,xmin::text FROM {snapshots.schema.OWNER} '
                            'WHERE id=1').fetchone()

    if existing:
        save_attempt(1)
    instance = 'attempt-close-qualifier'
    publish(operational, instance=instance)
    before = state(conn)
    original_owner = owner_version()
    prior = conn.execute(f"SELECT signature FROM {snapshots.schema.RECEIPTS} WHERE scope='DASHBOARD'").fetchone()
    conn.rollback()
    with monkeypatch.context() as race:
        race.setattr(readiness_handoff, 'capture', lambda *_a, **_kw: save_attempt(2))
        assert producer.collect_result(conn.info.dsn, owner, '/private', instance) == {'outcome': 'SUPERSEDED'}
    assert state(conn) == before
    assert conn.execute(f"SELECT signature FROM {snapshots.schema.RECEIPTS} WHERE scope='DASHBOARD'").fetchone() == prior
    current_owner = owner_version()
    assert current_owner[:2] == original_owner[:2]
    assert (current_owner[2] == original_owner[2]) == existing
    conn.rollback()
    assert producer.collect_result(conn.info.dsn, owner, '/private', instance)['outcome'] == 'PUBLISHED'
    details = producer.read(conn.info.dsn).trial_details['verification_attempts'][scope]
    assert details['latest']['attempt_id'] == f'{2:032x}' and details['latest']['outcome'] == 'RUNNING'


def test_negative_publication_allows_owner_renewal_before_its_write_fence(operational, monkeypatch):
    from sentinel.panel import observer_failure

    conn, owner, _ = operational
    prior = publish(operational)
    before = state(conn)
    diagnostic = observer_failure.failure('READ_TIMEOUT', 'OBSERVATION').model_dump(
        mode='json', by_alias=True)
    subjects = snapshots.subjects

    def renew(*args):
        value = subjects(*args)
        conn.execute("SET LOCAL lock_timeout='250ms'")
        conn.execute(f"UPDATE {snapshots.schema.OWNER} SET expires_at=clock_timestamp()+interval '610 seconds' "
                     'WHERE owner_id=%s', (owner,))
        conn.commit()
        return value

    with monkeypatch.context() as race:
        race.setattr(snapshots, 'subjects', renew)
        with pytest.raises(psycopg.errors.SerializationFailure):
            producer.publish_failure(conn.info.dsn, owner, 'one-verifier', diagnostic)
    assert state(conn) == before
    assert producer.read(conn.info.dsn).observation_valid_until.isoformat() == prior['valid_until']
    producer.publish_failure(conn.info.dsn, owner, 'one-verifier', diagnostic)
    assert producer.read(conn.info.dsn).row('operational_projection').status == model.UNKNOWN


@pytest.mark.parametrize('locked_attempts', [1, 2])
def test_actual_owner_lock_recovers_once_or_retains_typed_failure(operational, monkeypatch, locked_attempts):
    """Reproduce the incident's owner SELECT timeout on the private primary."""
    from psycopg.errors import QueryCanceled
    from sentinel.feed import store
    conn, owner_id, _ = operational
    publish(operational, instance='lock-qualifier')
    before = state(conn)
    conn.execute(f'SELECT id FROM {snapshots.schema.OWNER} WHERE id=1 FOR UPDATE')
    original_connect = store.connect
    def bounded(*args, **kwargs):
        kwargs['statement_timeout_ms'] = 500
        return original_connect(*args, **kwargs)
    monkeypatch.setattr(store, 'connect', bounded)
    original_publish = producer.publish_once
    attempts = []
    def collect(*args, **kwargs):
        attempts.append(len(attempts)+1)
        try:
            return original_publish(*args, **kwargs)
        except QueryCanceled:
            assert producer._COLLECTION_STAGE.get() == 'OWNER'
            if len(attempts) == locked_attempts:
                conn.rollback()  # Release only after the actual bounded refusal.
            raise
    monkeypatch.setattr(producer, 'publish_once', collect)
    started = time.monotonic()
    try:
        result = producer.collect_result(conn.info.dsn, owner_id, '/var/lib/sentinel', 'lock-qualifier')
    finally:
        conn.rollback()
    assert result['outcome'] == 'PUBLISHED'
    assert attempts == [1, 2] and time.monotonic()-started < producer.DEADLINE_SECONDS
    after = state(conn)
    if locked_attempts == 1:
        assert after['head'] == before['head'] and after['active'] == before['active'] == []
        assert conn.execute("SELECT count(*) FROM sentinel_dashboard_review_events WHERE kind='FAILED'").fetchone() == (0,)
    else:
        assert 'operational_projection' in after['active']
        event = conn.execute("SELECT payload FROM sentinel_dashboard_review_events WHERE kind='FAILED' ORDER BY sequence DESC LIMIT 1").fetchone()[0]
        evidence = event['details']['evidence']['operational_projection']
        assert evidence['code'] == 'OPERATIONAL_COLLECTION_READ_TIMEOUT'
        assert evidence['collector_stage'] == 'OWNER' and evidence['attempts'] == 2
        assert evidence['exception_type'] == 'QueryCanceled'


def test_review_and_snapshot_both_roll_back_if_publication_refuses(operational, monkeypatch):
    conn, _, condition = operational
    publish(operational)
    baseline = state(conn)
    previous = producer.read(conn.info.dsn)
    condition['broker'] = model.FAIL
    def refused(*_, **__):
        raise snapshots.SnapshotUnavailable('PRIVATE_PUBLICATION_REFUSAL')
    monkeypatch.setattr(snapshots, 'publish_owned', refused)
    with pytest.raises(snapshots.SnapshotUnavailable):
        publish(operational)
    assert state(conn) == baseline
    assert producer.read(conn.info.dsn).operator_review == previous.operator_review
    assert conn.execute('SELECT count(*) FROM sentinel_dashboard_review_events WHERE kind=%s',
                        ('FAILED',)).fetchone() == (0,)


def test_replaced_owner_cannot_record_review_or_publish_snapshot(operational):
    conn, owner_id, _ = operational
    conn.execute(f'UPDATE {snapshots.schema.OWNER} SET owner_id=%s', (str(uuid.uuid4()),))
    conn.commit()
    with pytest.raises(ValueError):
        compose_and_publish(conn.info.dsn, owner_id, '/var/lib/sentinel', 'stale-verifier')
    assert state(conn) is None
    assert conn.execute(f'SELECT count(*) FROM {snapshots.schema.RECEIPTS} WHERE scope=%s',
                        (snapshots.SCOPE,)).fetchone() == (0,)


def test_collection_superseded_by_native_revision_commits_neither_half(operational):
    from sentinel.panel import composition

    conn, owner_id, condition = operational
    def change_generation():
        conn.execute('UPDATE sentinel_automation_control SET generation=generation+1 WHERE id=1')
        conn.commit()
    condition['collect'] = change_generation
    with pytest.raises(producer.CollectionSuperseded, match='composition inputs changed'):
        composition.collect(conn.info.dsn, owner_id, '/var/lib/sentinel', 'one-verifier')
    assert not composition.path('one-verifier').exists()
    assert state(conn) is None
    assert conn.execute(f'SELECT count(*) FROM {snapshots.schema.RECEIPTS} WHERE scope=%s',
                        (snapshots.SCOPE,)).fetchone() == (0,)


def test_new_native_subject_refuses_old_snapshot_acknowledgement(operational):
    conn, _, _ = operational
    publish(operational)
    baseline = producer.read(conn.info.dsn)
    old_state = state(conn)
    conn.execute('UPDATE sentinel_automation_control SET generation=generation+1 WHERE id=1')
    conn.commit()
    with pytest.raises(ValueError):
        review.Recorder().acknowledge(baseline, conn.info.dsn, baseline.operator_review.token,
            actor='private qualifier', snapshot_guard=lambda c, p: producer.guard_acknowledgement(c, p, conn.info.dsn))
    assert state(conn) == old_state


def test_new_review_head_refuses_old_snapshot_acknowledgement(operational):
    conn, _, _ = operational
    publish(operational)
    baseline = producer.read(conn.info.dsn)
    producer.register_panel_incarnation(conn.info.dsn, 'new-panel-after-view')
    current = state(conn)
    assert current['head'] > baseline.operator_review.head
    with pytest.raises(ValueError):
        review.Recorder().acknowledge(baseline, conn.info.dsn, baseline.operator_review.token,
            actor='private qualifier', snapshot_guard=lambda c, p: producer.guard_acknowledgement(c, p, conn.info.dsn))
    assert state(conn) == current


def test_snapshot_gets_never_collect_or_record_a_new_incident(operational, monkeypatch):
    conn, _, _ = operational
    publish(operational)
    before = state(conn)
    from sentinel.panel import sources
    def forbidden(*_, **__):
        raise AssertionError('snapshot read attempted collection or review recording')
    monkeypatch.setattr(sources, 'build_panel', forbidden)
    monkeypatch.setattr(review.Recorder, 'observe_owned', forbidden)
    first, second = producer.read(conn.info.dsn), producer.read(conn.info.dsn)
    assert first.operator_review == second.operator_review
    assert state(conn) == before


def test_snapshot_publication_locks_serialize_against_ack_boundary(operational):
    conn, _, _ = operational
    publish(operational)
    baseline = producer.read(conn.info.dsn)
    producer.guard_acknowledgement(conn, baseline, conn.info.dsn)
    with psycopg.connect(conn.info.dsn) as writer:
        writer.execute("SET LOCAL lock_timeout='50ms'")
        with pytest.raises(psycopg.errors.LockNotAvailable):
            writer.execute(f'UPDATE {snapshots.schema.RECEIPTS} SET observed_at=observed_at WHERE scope=%s',
                           (snapshots.SCOPE,))
        writer.rollback()
    conn.rollback()
    assert state(conn)['head'] == baseline.operator_review.head


def financial_rows(scope, now):
    from sentinel.panel import read_projection
    if scope == 'PAPER':
        return [replace(model.paper_reconciliation_row(state='CLEAN'), as_of=now,
                        freshness=timedelta(seconds=600))]
    from tests.sentinel.test_shadow_content_projection import proof_rows
    return proof_rows(instant=now)


def save_financial(conn, scope, rows=None, *, errors=None):
    from psycopg.types.json import Jsonb
    from sentinel.panel import read_projection
    now = datetime.now(timezone.utc)
    native = read_projection.subject(conn, conn.info.dsn, scope)
    value, signed = read_projection.make(scope, native, rows or financial_rows(scope, now),
                                         errors or [], observed_at=now)
    conn.execute(f'INSERT INTO {snapshots.schema.RECEIPTS} VALUES(%s,%s,%s,%s,%s,%s) '
        'ON CONFLICT(scope) DO UPDATE SET subject_sha256=EXCLUDED.subject_sha256,'
        'observed_at=EXCLUDED.observed_at,valid_until=EXCLUDED.valid_until,'
        'envelope=EXCLUDED.envelope,signature=EXCLUDED.signature',
        (scope, native, value['observed_at'], value['valid_until'], Jsonb(value), signed))
    conn.commit()


def _publish_error_composition(operational, monkeypatch, tmp_path, *,
                               shadow_errors=(), shadow_rows=None, paper_errors=(), unrelated=(),
                               whole_read_error=None):
    from sentinel.panel import composition, read_projection, sources

    conn, owner, condition = operational
    condition['financial'] = True
    save_financial(conn, 'SHADOW', rows=shadow_rows, errors=list(shadow_errors))
    save_financial(conn, 'PAPER', errors=list(paper_errors))
    base = sources.build_panel

    def build(**kwargs):
        page = base(**kwargs)
        financial, _, _, errors, by_scope = read_projection.read(
            conn.info.dsn, with_error_scopes=True)
        owned = ({'GLOBAL': [whole_read_error]}
                 if whole_read_error is not None else by_scope)
        financial_errors = ([whole_read_error]
                            if whole_read_error is not None else errors)
        selected = {row.key: row for row in financial}
        return replace(page,
            rows=[selected.get(row.key, row) for row in page.rows],
            source_errors=[*unrelated, *financial_errors],
            financial_source_errors=owned)

    monkeypatch.setattr(sources, 'build_panel', build)
    monkeypatch.setattr(composition.tempfile, 'gettempdir', lambda: str(tmp_path))
    instance = str(uuid.uuid4())
    composition.collect(conn.info.dsn, owner, '/private', instance)
    producer.publish_once(conn.info.dsn, owner, '/private', instance)
    return conn, owner, instance


def _assert_clean_paper_receipt_clears_error(operational, monkeypatch, tmp_path):
    conn, owner, instance = _publish_error_composition(
        operational, monkeypatch, tmp_path, paper_errors=('PAPER source failed',))
    assert producer.read(conn.info.dsn).source_errors == ['PAPER source failed']
    save_financial(conn, 'PAPER')
    current = producer.read(conn.info.dsn, display=True)
    assert current.observation_changed_scopes == ('PAPER',)
    assert current.source_errors == []
    assert current.financial_source_errors['PAPER'] == []
    producer.publish_once(conn.info.dsn, owner, '/private', instance)
    published = producer.read(conn.info.dsn)
    assert published.source_errors == []
    assert 'backend_sources' not in state(conn)['active']


def test_clean_receipt_retires_old_source_error_on_read_and_fast_publication(
        operational, monkeypatch, tmp_path):
    _assert_clean_paper_receipt_clears_error(operational, monkeypatch, tmp_path)


def test_stale_financial_source_error_guard_has_a_real_receipt_falsifier(
        operational, monkeypatch, tmp_path):
    monkeypatch.setattr(producer, '_replace_financial_source_errors',
                        lambda panel, _refreshed: panel)
    with pytest.raises(AssertionError, match='.*'):
        _assert_clean_paper_receipt_clears_error(operational, monkeypatch, tmp_path)


def test_paper_receipt_replacement_preserves_shadow_and_nonfinancial_errors(
        operational, monkeypatch, tmp_path):
    conn, owner, instance = _publish_error_composition(
        operational, monkeypatch, tmp_path,
        shadow_errors=('shared source text',), paper_errors=('shared source text',),
        unrelated=('shared source text', 'unrelated source failed'))
    assert producer.read(conn.info.dsn).source_errors.count('shared source text') == 3
    save_financial(conn, 'PAPER')
    current = producer.read(conn.info.dsn, display=True)
    assert current.source_errors.count('shared source text') == 2
    assert 'unrelated source failed' in current.source_errors
    assert current.financial_source_errors['SHADOW'] == ['shared source text']
    producer.publish_once(conn.info.dsn, owner, '/private', instance)
    published = producer.read(conn.info.dsn)
    assert published.source_errors.count('shared source text') == 2
    assert 'unrelated source failed' in published.source_errors
    assert published.financial_source_errors['SHADOW'] == ['shared source text']


def test_changed_review_head_keeps_duplicate_error_ownership_during_paper_refresh(
        operational, monkeypatch, tmp_path):
    conn, _, _ = _publish_error_composition(
        operational, monkeypatch, tmp_path,
        shadow_errors=('shared source text',), paper_errors=('shared source text',),
        unrelated=('shared source text',))
    key, now = review_store.scope(conn), review_store.database_now(conn)
    reviewed = review_store.load_locked(conn, key, now)
    assert 'backend_sources' in reviewed['active']
    review_store.append(conn, key, reviewed, kind='REVIEW',
        event_key='independent-review-head:'+str(reviewed['head']+1),
        details={'reason':'independent signed review event'}, now=now)
    review_store.save(conn, key, reviewed, now)
    conn.commit()
    save_financial(conn, 'PAPER')
    current = producer.read(conn.info.dsn, display=True)
    assert current.observation_changed_scopes == ('PAPER',)
    assert current.observation_retained
    assert current.source_errors.count('shared source text') == 2
    assert current.source_errors.count(
        'Current signed review records active conditions; current display composition is pending.') == 1
    assert current.financial_source_errors['SHADOW'] == ['shared source text']


def test_owned_receipt_read_retires_prior_whole_financial_read_failure(
        operational, monkeypatch, tmp_path):
    conn, owner, instance = _publish_error_composition(
        operational, monkeypatch, tmp_path,
        whole_read_error='financial verification: durable read unavailable')
    save_financial(conn, 'PAPER')
    current = producer.read(conn.info.dsn, display=True)
    assert current.source_errors == []
    assert 'GLOBAL' not in current.financial_source_errors
    producer.publish_once(conn.info.dsn, owner, '/private', instance)
    published = producer.read(conn.info.dsn)
    assert published.source_errors == []
    assert 'GLOBAL' not in published.financial_source_errors


def _assert_whole_read_checks_unchanged_shadow(operational, monkeypatch, tmp_path):
    from sentinel.panel import authority_reader

    shadow_rows = authority_reader._unknown(False, 'SHADOW source failed')[0]
    conn, owner, instance = _publish_error_composition(
        operational, monkeypatch, tmp_path, shadow_rows=shadow_rows,
        shadow_errors=('SHADOW source failed',),
        whole_read_error='financial verification: PlanRolloutMismatch')
    save_financial(conn, 'PAPER')
    current = producer.read(conn.info.dsn, display=True)
    assert current.source_errors == ['SHADOW source failed']
    assert current.financial_source_errors['SHADOW'] == ['SHADOW source failed']
    assert 'GLOBAL' not in current.financial_source_errors
    assert current.row('shadow_verification').status == model.UNKNOWN
    producer.publish_once(conn.info.dsn, owner, '/private', instance)
    published = producer.read(conn.info.dsn)
    assert published.source_errors == ['SHADOW source failed']
    assert published.financial_source_errors['SHADOW'] == ['SHADOW source failed']


def test_whole_financial_error_requires_resampling_unchanged_shadow(
        operational, monkeypatch, tmp_path):
    _assert_whole_read_checks_unchanged_shadow(operational, monkeypatch, tmp_path)


def test_omitting_unchanged_shadow_resample_has_a_real_receipt_falsifier(
        operational, monkeypatch, tmp_path):
    from sentinel.panel import read_projection

    def only_changed(conn, database_url, _panel, *, now, changed, facts, basis):
        assert changed == ('PAPER',)
        rows, _, _, _, owned = read_projection.read_owned(
            conn, database_url, now=now, only_scope='PAPER', facts=facts,
            native_subjects=basis.get('native'), display_basis=basis or None,
            with_error_scopes=True)
        return {row.key: row for row in rows}, owned

    monkeypatch.setattr(producer, '_financial_receipt_overlay', only_changed)
    with pytest.raises(AssertionError, match='.*'):
        _assert_whole_read_checks_unchanged_shadow(operational, monkeypatch, tmp_path)


def test_failed_whole_financial_resample_keeps_error_and_reads_changed_paper(
        operational, monkeypatch, tmp_path):
    from sentinel.panel import read_projection

    conn, owner, instance = _publish_error_composition(
        operational, monkeypatch, tmp_path,
        whole_read_error='financial verification: PlanRolloutMismatch')
    save_financial(conn, 'PAPER')
    original = read_projection.read_owned

    def fails_full_in_sql(actual, database_url, **kwargs):
        if kwargs.get('only_scope') is None and kwargs.get('with_error_scopes'):
            actual.execute('SELECT 1/0')  # Aborts this transaction until savepoint rollback.
        return original(actual, database_url, **kwargs)

    monkeypatch.setattr(read_projection, 'read_owned', fails_full_in_sql)
    current = producer.read(conn.info.dsn, display=True)
    assert current.source_errors == ['financial verification: PlanRolloutMismatch']
    assert current.financial_source_errors == {
        'GLOBAL': ['financial verification: PlanRolloutMismatch'], 'PAPER': []}
    assert current.row('paper_reconciliation').status == model.OK
    assert 'paper_reconciliation' in current.observation_revalidated_keys
    producer.publish_once(conn.info.dsn, owner, '/private', instance)
    published = producer.read(conn.info.dsn)
    assert published.source_errors == ['financial verification: PlanRolloutMismatch']
    assert published.row('paper_reconciliation').status == model.OK


def test_changed_paper_subject_keeps_independent_shadow_proof_and_original_clock(operational):
    conn, _, condition = operational
    condition['financial'] = True
    save_financial(conn, 'SHADOW')
    save_financial(conn, 'PAPER')
    publish(operational)
    before = producer.read(conn.info.dsn)
    conn.execute('UPDATE sentinel_automation_control SET generation=generation+1 WHERE id=1')
    conn.commit()
    changed = producer.read(conn.info.dsn)
    assert changed.observation_current is False and changed.observation_changed_scopes == ('PAPER',)
    assert changed.row('book') == before.row('book')
    assert changed.row('book').can_show_shadow_book(changed.now)
    assert changed.row('shadow_verification') == before.row('shadow_verification')
    assert changed.row('paper_reconciliation').status == model.WARN
    assert not changed.source_errors


def test_same_subject_new_negative_financial_receipt_wins_before_next_collection(operational):
    from sentinel.panel import presentation, read_projection
    conn, _, condition = operational
    condition['financial'] = True
    save_financial(conn, 'SHADOW')
    save_financial(conn, 'PAPER')
    publish(operational)
    before = producer.read(conn.info.dsn)
    native = read_projection.subject(conn, conn.info.dsn, 'PAPER')
    conn.rollback()
    save_financial(conn, 'PAPER', [model.paper_reconciliation_row(state='MISMATCH')])
    assert read_projection.subject(conn, conn.info.dsn, 'PAPER') == native
    conn.rollback()
    changed = producer.read(conn.info.dsn)
    assert changed.observation_current is False and changed.observation_changed_scopes == ('PAPER',)
    assert changed.row('book') == before.row('book')
    assert changed.row('paper_reconciliation').effective_status(changed.now) == model.FAIL
    assert presentation.dashboard_health(changed)['status'] == model.FAIL


def test_verifier_owner_swap_withdraws_previous_clean_snapshot_before_restart_event(operational):
    conn, _, _ = operational
    publish(operational)
    initial = producer.read(conn.info.dsn)
    review.Recorder().acknowledge(initial, conn.info.dsn, initial.operator_review.token,
        actor='private qualifier', snapshot_guard=lambda c, p: producer.guard_acknowledgement(c, p, conn.info.dsn))
    publish(operational)
    clean = producer.read(conn.info.dsn)
    assert clean.operator_review.status == 'CLEAN'
    before_context, before_subjects = snapshots.context(conn, conn.info.dsn), snapshots.subjects(conn, conn.info.dsn)
    conn.rollback()
    before_state = state(conn)
    conn.execute(f'UPDATE {snapshots.schema.OWNER} SET owner_id=%s', (str(uuid.uuid4()),))
    conn.commit()
    assert snapshots.context(conn, conn.info.dsn) != before_context
    assert snapshots.subjects(conn, conn.info.dsn) == before_subjects
    conn.rollback()
    with pytest.raises(snapshots.SnapshotUnavailable): producer.read(conn.info.dsn)
    assert state(conn) == before_state  # No HTTP-driven restart/incident write.


def test_acknowledgement_guard_freezes_owner_replacement_until_transaction_ends(operational):
    conn, _, _ = operational
    publish(operational)
    baseline = producer.read(conn.info.dsn)
    producer.guard_acknowledgement(conn, baseline, conn.info.dsn)
    replacement = str(uuid.uuid4())
    with psycopg.connect(conn.info.dsn) as other:
        other.execute("SET LOCAL lock_timeout='50ms'")
        with pytest.raises(psycopg.errors.LockNotAvailable):
            other.execute(f'UPDATE {snapshots.schema.OWNER} SET owner_id=%s', (replacement,))
        other.rollback()
        conn.rollback()
        other.execute(f'UPDATE {snapshots.schema.OWNER} SET owner_id=%s', (replacement,))
    assert conn.execute(f'SELECT owner_id::text FROM {snapshots.schema.OWNER}').fetchone() == (replacement,)


def test_removed_acknowledgement_owner_lock_is_detected(operational, monkeypatch):
    code = inspect.getsource(producer.guard_acknowledgement)
    guard = 'expires_at>clock_timestamp() FOR SHARE'
    assert code.count(guard) == 1
    namespace = {}
    exec(compile(code.replace(guard, 'expires_at>clock_timestamp()'),
                 '<removed-acknowledgement-owner-lock>', 'exec'), vars(producer), namespace)
    monkeypatch.setattr(producer, 'guard_acknowledgement', namespace['guard_acknowledgement'])
    with pytest.raises(pytest.fail.Exception):
        test_acknowledgement_guard_freezes_owner_replacement_until_transaction_ends(operational)


def test_new_negative_row_absent_from_retained_snapshot_is_appended(operational):
    from sentinel.panel import presentation
    conn, _, _ = operational
    save_financial(conn, 'SHADOW')
    save_financial(conn, 'PAPER')
    publish(operational)
    baseline = producer.read(conn.info.dsn)
    assert baseline.row('paper_reconciliation') is None
    before_state = state(conn)
    save_financial(conn, 'PAPER', [model.paper_reconciliation_row(state='MISMATCH')])
    current = producer.read(conn.info.dsn)
    assert current.observation_changed_scopes == ('PAPER',)
    assert current.row('paper_reconciliation').effective_status(current.now) == model.FAIL
    assert 'paper_reconciliation' in current.observation_revalidated_keys
    assert presentation.dashboard_health(current)['status'] == model.FAIL
    assert state(conn) == before_state


def test_authenticated_snapshot_without_operator_review_has_controlled_refusal(operational):
    conn, owner_id, _ = operational
    publish(operational)
    now = review_store.database_now(conn)
    context, subjects = snapshots.context(conn, conn.info.dsn), snapshots.subjects(conn, conn.info.dsn)
    original = snapshots.read_owned(conn, context_sha256=context, now=now)
    envelope, signature = snapshots.encode(replace(original.panel, operator_review=None),
        context_sha256=context, subjects=subjects, valid_until=original.valid_until)
    snapshots.publish_owned(conn, owner_id=owner_id, value=envelope, signature=signature,
        context_sha256=context, subjects=subjects, now=now)
    conn.commit()
    with pytest.raises(snapshots.SnapshotUnavailable, match='review observation missing'):
        producer.read(conn.info.dsn)


def test_removed_collection_subject_binding_is_detected(operational, monkeypatch):
    conn, _, _ = operational
    original = producer._coordinates(conn.info.dsn)
    monkeypatch.setattr(producer, '_coordinates', lambda _: original)
    with pytest.raises(pytest.fail.Exception):
        test_collection_superseded_by_native_revision_commits_neither_half(operational)


def test_receipt_consumer_reads_only_the_requested_scope_and_its_errors(operational):
    from sentinel.panel import read_projection
    conn, _, _ = operational
    save_financial(conn, 'PAPER')
    rows, _, _, errors = read_projection.read(conn.info.dsn, only_scope='PAPER')
    assert len(rows) == 1 and rows[0].key == 'paper_reconciliation'
    assert rows[0].status == model.OK and not errors
    # The independent shadow receipt is genuinely unavailable in this fixture.
    all_rows, _, _, all_errors = read_projection.read(conn.info.dsn)
    assert any(row.key == 'shadow_verification' and row.status == model.UNKNOWN for row in all_rows)
    assert all_errors


@pytest.mark.parametrize('scope,paper', [('DASHBOARD', True), ('unknown', True), ('PAPER', False)])
def test_unknown_or_contradictory_selected_receipt_scope_refuses_before_io(monkeypatch, scope, paper):
    from sentinel.feed import store
    from sentinel.panel import read_projection
    def forbidden(*_, **__): raise AssertionError('invalid scope opened a connection')
    monkeypatch.setattr(store, 'connect', forbidden)
    with pytest.raises(ValueError, match='scope'):
        read_projection.read('unused', only_scope=scope, include_paper=paper)


def test_owner_original_expiry_caps_the_operational_snapshot(operational):
    conn, _, _ = operational
    expiry = conn.execute(f'UPDATE {snapshots.schema.OWNER} SET '
        "expires_at=clock_timestamp()+interval '20 seconds' RETURNING expires_at").fetchone()[0]
    conn.commit()
    publish(operational)
    stored = conn.execute(f'SELECT valid_until FROM {snapshots.schema.RECEIPTS} WHERE scope=%s',
                          (snapshots.SCOPE,)).fetchone()[0]
    assert stored == expiry
    assert conn.execute(f'SELECT expires_at FROM {snapshots.schema.OWNER}').fetchone() == (expiry,)


def test_expired_owner_cannot_create_review_history_or_a_snapshot(operational):
    conn, _, _ = operational
    conn.execute(f'UPDATE {snapshots.schema.OWNER} SET expires_at=clock_timestamp()-interval \'1 second\'')
    conn.commit()
    with pytest.raises(snapshots.SnapshotUnavailable): publish(operational)
    assert state(conn) is None


def test_incarnation_history_distinguishes_projector_and_panel_without_gets(operational):
    conn, _, _ = operational
    publish(operational, instance='one-verifier')
    first = state(conn)
    producer.register_panel_incarnation(conn.info.dsn, 'one-panel')
    registered = state(conn)
    producer.register_panel_incarnation(conn.info.dsn, 'one-panel')
    assert state(conn) == registered and registered['head'] == first['head']+1
    components = [row[0]['details']['component'] for row in conn.execute(
        "SELECT payload FROM sentinel_dashboard_review_events WHERE kind='STARTED' ORDER BY sequence").fetchall()]
    assert components == ['verifier', 'dashboard']


def test_panel_start_before_first_snapshot_keeps_review_state_loadable(operational):
    conn, _, _ = operational
    producer.register_panel_incarnation(conn.info.dsn, 'first-panel')
    key = review_store.scope(conn)
    initial = review_store.load_locked(conn, key, review_store.database_now(conn))
    assert initial['head'] == 1 and initial['reviewed_head'] == 0
    conn.rollback()
    publish(operational)
    assert producer.read(conn.info.dsn).operator_review.status == 'REVIEW'


def test_configured_http_startup_refuses_real_registration_lock_then_records_new_incarnation(operational, monkeypatch):
    import importlib
    from pathlib import Path
    from fastapi.testclient import TestClient
    app = importlib.import_module('sentinel.panel.app')
    conn, _, _ = operational
    monkeypatch.setattr(app, '_config', lambda: (Path('/var/lib/sentinel'), conn.info.dsn))
    monkeypatch.setattr(app.recorder, 'instance', 'blocked-private-panel')
    conn.execute('LOCK TABLE sentinel_dashboard_review_state IN ACCESS EXCLUSIVE MODE')
    with pytest.raises(RuntimeError, match='durable incarnation registration'):
        with TestClient(app.app):
            pytest.fail('HTTP startup bypassed the real unavailable review store')
    conn.rollback()
    assert state(conn) is None
    monkeypatch.setattr(app.recorder, 'instance', 'recovered-private-panel')
    with TestClient(app.app) as client:
        initial = state(conn)
        assert initial['head'] == 1 and initial['reviewed_head'] == 0
        publish(operational)
        response = client.get('/panel.json')
        assert response.status_code == 200
        assert response.json()['operator_review']['status'] == 'REVIEW'
    events = conn.execute('SELECT event_key FROM sentinel_dashboard_review_events ORDER BY sequence').fetchall()
    assert ('dashboard:recovered-private-panel',) in events
    assert ('dashboard:blocked-private-panel',) not in events


def test_broken_public_renderer_rolls_back_primary_publication(operational, monkeypatch):
    import importlib
    renderer = importlib.import_module('sentinel.panel.render')
    conn, owner_id, _ = operational
    publish(operational)
    baseline = state(conn)
    previous = producer.read(conn.info.dsn)
    def broken(*_, **__): raise ValueError('private deterministic renderer fault')
    monkeypatch.setattr(renderer, 'render', broken)
    with pytest.raises(ValueError):
        producer.publish_once(conn.info.dsn, owner_id, '/var/lib/sentinel', 'one-verifier')
    assert state(conn) == baseline
    assert producer.read(conn.info.dsn).operator_review == previous.operator_review


def test_broken_renderer_publishes_current_negative_without_retained_values_or_secrets(operational, monkeypatch):
    import importlib
    import json
    from sentinel.panel import presentation
    renderer = importlib.import_module('sentinel.panel.render')
    conn, owner_id, condition = operational
    condition['financial'] = True
    save_financial(conn, 'SHADOW')
    save_financial(conn, 'PAPER')
    publish(operational)
    before = producer.read(conn.info.dsn)
    secret = 'postgresql://private-user:never-record-this-password@private-host/source'
    with monkeypatch.context() as changed:
        def broken(*_, **__): raise ValueError(secret)
        changed.setattr(renderer, 'render', broken)
        outcome = producer.collect_result(conn.info.dsn, owner_id, '/var/lib/sentinel', 'one-verifier')
    assert outcome['outcome'] == 'PUBLISHED'
    failed = producer.read(conn.info.dsn)
    assert presentation.dashboard_health(failed)['status'] == model.FAIL
    assert failed.operator_review.status == 'FAILED'
    assert failed.row('book') is None and failed.row('alpaca_account') is None
    assert failed.row('operational_projection').status == model.UNKNOWN
    assert all(row.shadow_book is None and row.paper_account is None for row in failed.rows)
    stored = conn.execute(f'SELECT envelope FROM {snapshots.schema.RECEIPTS} WHERE scope=%s',
                          (snapshots.SCOPE,)).fetchone()[0]
    history = conn.execute('SELECT payload FROM sentinel_dashboard_review_events').fetchall()
    assert secret not in json.dumps([stored, history]) and 'never-record-this-password' not in str(stored)
    conn.rollback()
    assert failed.operator_review.head > before.operator_review.head
    publish(operational)
    recovered = producer.read(conn.info.dsn)
    assert recovered.operator_review.status == 'REVIEW'
    assert any(event['kind'] == 'RECOVERED' for event in recovered.operator_review.events)


def test_removed_public_projection_preflight_is_detected(operational, monkeypatch):
    from sentinel.panel import serialization
    monkeypatch.setattr(serialization, 'preflight', lambda *_: None)
    with pytest.raises(pytest.fail.Exception):
        test_broken_public_renderer_rolls_back_primary_publication(operational, monkeypatch)


def test_private_component_timings_are_measured_without_production_claim(operational, record_property, monkeypatch):
    import importlib
    from pathlib import Path
    from fastapi.testclient import TestClient
    app = importlib.import_module('sentinel.panel.app')
    conn, _, condition = operational
    condition['financial'] = condition['rich'] = True
    save_financial(conn, 'SHADOW')
    save_financial(conn, 'PAPER')
    monkeypatch.setattr(app, '_config', lambda: (Path('/var/lib/sentinel'), conn.info.dsn))
    measurements = {'producer_seconds': [], 'http_json_seconds': [], 'http_html_seconds': []}
    with TestClient(app.app) as client:
        for _ in range(2):
            started = time.monotonic()
            publish(operational)
            measurements['producer_seconds'].append(time.monotonic()-started)
            before = state(conn)
            started = time.monotonic()
            observed = client.get('/panel.json')
            measurements['http_json_seconds'].append(time.monotonic()-started)
            assert observed.status_code == 200
            assert next(row for row in observed.json()['rows'] if row['key'] == 'book')['shadow_book']
            started = time.monotonic()
            html = client.get('/?document=1')
            measurements['http_html_seconds'].append(time.monotonic()-started)
            assert html.status_code == 200 and 'text/html' in html.headers['content-type']
            assert state(conn) == before
    record_property('private_component_timings', measurements)
    print('PRIVATE_SYNTHETIC_COMPONENT_TIMINGS', measurements)
