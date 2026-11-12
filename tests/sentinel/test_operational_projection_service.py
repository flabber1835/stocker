"""Actual PostgreSQL operational ownership, review/snapshot atomicity and ACK."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import inspect
import time
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


def save_financial(conn, scope, rows=None):
    from psycopg.types.json import Jsonb
    from sentinel.panel import read_projection
    now = datetime.now(timezone.utc)
    native = read_projection.subject(conn, conn.info.dsn, scope)
    value, signed = read_projection.make(scope, native, rows or financial_rows(scope, now), [], observed_at=now)
    conn.execute(f'INSERT INTO {snapshots.schema.RECEIPTS} VALUES(%s,%s,%s,%s,%s,%s) '
        'ON CONFLICT(scope) DO UPDATE SET subject_sha256=EXCLUDED.subject_sha256,'
        'observed_at=EXCLUDED.observed_at,valid_until=EXCLUDED.valid_until,'
        'envelope=EXCLUDED.envelope,signature=EXCLUDED.signature',
        (scope, native, value['observed_at'], value['valid_until'], Jsonb(value), signed))
    conn.commit()


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
