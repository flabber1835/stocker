"""Typed operational snapshots preserve evidence and caller-owned transactions."""
from copy import deepcopy
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import inspect
import json
import uuid

import psycopg
from psycopg import sql
import pytest

from sentinel.panel import model, operational_snapshot as snapshot, review_store
from sentinel.paper_plan_preview import PlanPreview, PlannedLeg
from tests.support.postgres import _EphemeralPostgres

NOW = datetime(2031, 4, 21, 20, tzinfo=timezone.utc)
CONTEXT = 'a' * 64
SUBJECTS = {'SHADOW': 'b' * 64, 'PAPER': 'c' * 64}


@pytest.fixture(autouse=True)
def signing_key(monkeypatch):
    monkeypatch.setenv('SENTINEL_PUBLICATION_RECEIPT_KEY', 'private-qualification-' + 'x' * 40)


def panel(now=NOW):
    plan = PlanPreview(cycle_id='cycle', plan_id='plan', decision_session=now.date(),
        effective_session=now.date()+timedelta(days=1), execute_at=now + timedelta(hours=17),
        created_at=now-timedelta(minutes=5), observation_at=now-timedelta(minutes=6),
        legs=[PlannedLeg(security_id='1', ticker='AAA', current_quantity=Decimal('1'),
            target_quantity=Decimal('1'), change_quantity=Decimal('0'), action='HOLD')])
    book = model.ShadowBook(session=str(now.date()), cash='50', receivables='0', nav='100',
        pending_operations=0, holdings=[model.ShadowHolding(security_id='1', ticker='AAA',
            quantity='1', raw_close='50', value='50', weight='.5')],
        slots=[model.ShadowSlot(slot_id=0, state='OCCUPIED', security_id='1', ticker='AAA',
            model_quantity='1', cooldown_total=20)])
    account = model.PaperAccountOverview(account_id='paper', equity='100', cash='50',
        buying_power='50', observed_at=now-timedelta(seconds=2))
    order = model.PaperOrderOutcome(security_id='1', ticker='AAA', client_key='command',
        broker_order_id='native', side='BUY', quantity='1', filled_quantity='1',
        state='FILLED', observed_at=now-timedelta(minutes=1))
    progress = model.PreparationWork(job_id='job', decision_session=now.date(),
        effective_session=now.date()+timedelta(days=1), state='ACQUIRING', rows_done=10, components_done=1,
        created_at=now-timedelta(minutes=1), updated_at=now, last_progress_at=now,
        observed_at=now, deadline=now+timedelta(hours=1), lease_until=now+timedelta(seconds=25),
        owner_registered=True, fence=1)
    return model.Panel(now=now, local_paper_mode=True, trial_details={'dated': 'retained'},
        trial_history=[{'verdict': 'NOT_VERIFIED'}], rows=[
        model.Row('book', 'Book', 'VERIFIED', shadow_book=book, as_of=now-timedelta(seconds=4),
            freshness=timedelta(minutes=10), required_current=True),
        model.Row('paper_plan', 'Plan', 'SAVED', paper_plan=plan, as_of=plan.created_at),
        model.Row('trading_run', 'Run', 'WAITING_OPEN', trading_run=model.TradingRun(
            intent=plan, state='WAITING_OPEN', updated_at=plan.created_at)),
        model.Row('alpaca_account', 'Account', 'ACTIVE', paper_account=account,
            order_outcomes=[order], as_of=account.observed_at, freshness=timedelta(seconds=45)),
        model.Row('ingest', 'Data', 'ACQUIRING', preparation=progress, as_of=now,
            valid_until=now+timedelta(seconds=25)),
        model.Row('paper_reconciliation', 'Alignment', 'PENDING', model.WARN, as_of=now,
            required_current=True, valid_until=now+timedelta(seconds=20),
            operational_fact=model.OperationalFact(kind='PAPER_VERIFICATION', state='CHECKING'),
            recovery=model.RecoveryEvidence(phase='FINANCIAL_VERIFICATION', automatic=True,
                deadline=now+timedelta(seconds=20))),
        model.Row('exposure', 'Exposure', '.55', operational_fact=model.OperationalFact(
            kind='CONTROLLER_DECISION', state='ADOPTED', session=now.date(),
            exposure=Decimal('.55'))),
    ])


def encode(page=None):
    return snapshot.encode(page or panel(), context_sha256=CONTEXT, subjects=SUBJECTS)


def decode(value, signed, **changes):
    return snapshot.decode(value, signed, context_sha256=changes.get('context_sha256', CONTEXT),
                           now=changes.get('now', NOW))


def test_roundtrip_preserves_every_nested_schema_and_original_clocks():
    original = panel()
    value, signed = encode(original)
    restored = decode(json.loads(json.dumps(value)), signed, now=NOW+timedelta(seconds=3))
    assert restored.panel == original
    assert restored.generated_at == restored.panel.now == NOW
    assert restored.valid_until == NOW+timedelta(seconds=20)
    assert restored.subjects == SUBJECTS
    assert isinstance(restored.panel.row('book').shadow_book.holdings[0].quantity, Decimal)
    assert isinstance(restored.panel.row('paper_plan').paper_plan, PlanPreview)
    assert isinstance(restored.panel.row('trading_run').trading_run, model.TradingRun)
    assert isinstance(restored.panel.row('ingest').preparation, model.PreparationWork)
    assert isinstance(restored.panel.row('alpaca_account').paper_account, model.PaperAccountOverview)
    assert isinstance(restored.panel.row('alpaca_account').order_outcomes[0], model.PaperOrderOutcome)
    assert isinstance(restored.panel.row('paper_reconciliation').recovery, model.RecoveryEvidence)
    fact = restored.panel.row('exposure').operational_fact
    assert isinstance(fact, model.OperationalFact) and fact.session == date(2031, 4, 21)
    assert fact.exposure == Decimal('.55')


def test_paper_subject_change_is_exposed_without_erasing_independent_shadow():
    value, signed = encode()
    before = decode(value, signed)
    changed = {**SUBJECTS, 'PAPER': 'd'*64}
    assert before.subjects['PAPER'] != changed['PAPER']
    assert before.subjects['SHADOW'] == changed['SHADOW']
    assert before.panel.row('book').can_show_shadow_book(NOW)


@pytest.mark.parametrize('change', ['tamper', 'purpose', 'context', 'expiry', 'future', 'naive'])
def test_snapshot_rejects_wrong_authentication_scope_and_clocks(change):
    value, signed = encode()
    arguments = {}
    if change == 'tamper':
        value['panel']['rows'][0]['value'] = 'forged'
    elif change == 'purpose':
        signed = review_store.signature(value, purpose='sentinel.operational-verification/1')
    elif change == 'context':
        arguments['context_sha256'] = 'e'*64
    elif change == 'expiry':
        arguments['now'] = NOW+timedelta(seconds=20)
    elif change == 'future':
        arguments['now'] = NOW-timedelta(microseconds=1)
    else:
        arguments['now'] = NOW.replace(tzinfo=None)
    with pytest.raises(snapshot.SnapshotUnavailable):
        decode(value, signed, **arguments)


def test_removed_signature_guard_is_detected(monkeypatch):
    monkeypatch.setattr(snapshot.hmac, 'compare_digest', lambda *_: True)
    with pytest.raises(pytest.fail.Exception):
        test_snapshot_rejects_wrong_authentication_scope_and_clocks('tamper')


@pytest.mark.parametrize('defect', ['unknown_panel_field', 'unknown_row_field', 'duplicate_row',
    'unknown_status', 'naive_row', 'invalid_account', 'invalid_book', 'string_recovery_flag',
    'consumer_noncurrent', 'consumer_scopes', 'consumer_boundary', 'consumer_revalidated', 'foreign_workflow_fact'])
def test_authenticated_malformed_payload_never_bypasses_existing_models(defect):
    value, _ = encode()
    rows = value['panel']['rows']
    if defect == 'unknown_panel_field': value['panel']['unexpected'] = True
    elif defect == 'unknown_row_field': rows[0]['unexpected'] = True
    elif defect == 'duplicate_row': rows.append(deepcopy(rows[0]))
    elif defect == 'unknown_status': rows[0]['status'] = 'healthy'
    elif defect == 'naive_row': rows[0]['as_of'] = NOW.replace(tzinfo=None).isoformat()
    elif defect == 'invalid_account': rows[3]['paper_account']['cash'] = '101'
    elif defect == 'invalid_book': rows[0]['shadow_book']['nav'] = '101'
    elif defect == 'string_recovery_flag': rows[-2]['recovery']['automatic'] = 'true'
    elif defect == 'consumer_noncurrent': value['panel']['observation_current'] = False
    elif defect == 'consumer_scopes': value['panel']['observation_changed_scopes'] = ['PAPER']
    elif defect == 'consumer_boundary': value['panel']['observation_valid_until'] = (NOW+timedelta(seconds=20)).isoformat()
    elif defect == 'consumer_revalidated': value['panel']['observation_revalidated_keys'] = ['book']
    else: rows[0]['operational_fact'] = rows[-2]['operational_fact']
    signed = review_store.signature(value, purpose=snapshot.PURPOSE)
    with pytest.raises(snapshot.SnapshotUnavailable):
        decode(value, signed)


def test_snapshots_cannot_extend_original_row_expiry_or_maximum_lifetime():
    with pytest.raises(snapshot.SnapshotUnavailable, match='EXPIRY'):
        snapshot.encode(panel(), context_sha256=CONTEXT, subjects=SUBJECTS,
                        valid_until=NOW+timedelta(seconds=21))
    simple = model.Panel(rows=[model.Row('known_failure', 'Fact', 'FAILED', model.FAIL)], now=NOW)
    value, signed = encode(simple)
    assert decode(value, signed).valid_until == NOW+timedelta(seconds=30)
    value['valid_until'] = (NOW+timedelta(seconds=31)).isoformat()
    signed = review_store.signature(value, purpose=snapshot.PURPOSE)
    with pytest.raises(snapshot.SnapshotUnavailable): decode(value, signed)


def test_removed_original_expiry_guard_is_detected(monkeypatch):
    code = inspect.getsource(snapshot.encode)
    guard = "_require(_utc(expiry) and panel.now < expiry <= boundary, 'SNAPSHOT_EXPIRY_INVALID')"
    assert guard in code
    namespace = {}
    exec(compile(code.replace(guard, 'pass'), '<removed-original-snapshot-expiry>', 'exec'),
         vars(snapshot), namespace)
    monkeypatch.setattr(snapshot, 'encode', namespace['encode'])
    with pytest.raises(pytest.fail.Exception):
        test_snapshots_cannot_extend_original_row_expiry_or_maximum_lifetime()


def test_snapshot_size_bound_applies_before_publication_and_decode():
    large = replace(panel(), trial_details={'oversized': 'x'*snapshot.MAX_BYTES})
    with pytest.raises(snapshot.SnapshotUnavailable, match='SIZE'):
        encode(large)
    value, _ = encode()
    value['panel']['trial_details'] = {'oversized': 'x'*snapshot.MAX_BYTES}
    with pytest.raises(snapshot.SnapshotUnavailable, match='SIZE'):
        decode(value, 'a'*64)


@pytest.fixture(scope='module')
def pg():
    server = _EphemeralPostgres()
    server.start()
    try: yield server
    finally: server.stop()


@pytest.fixture
def conn(pg):
    database = 'snapshot_'+uuid.uuid4().hex
    with psycopg.connect(pg.sync_dsn, autocommit=True) as admin:
        admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(database)))
    connection = psycopg.connect(pg.sync_dsn.rsplit('/', 1)[0]+'/'+database)
    # Use the exact installed receipt/owner table definitions, without unrelated DDL.
    for statement in snapshot.schema.DDL:
        if statement.startswith(('CREATE TABLE '+snapshot.schema.RECEIPTS+' ',
                                 'CREATE TABLE '+snapshot.schema.OWNER+' ')):
            connection.execute(statement)
    connection.commit()
    try: yield connection
    finally:
        connection.close()
        with psycopg.connect(pg.sync_dsn, autocommit=True) as admin:
            admin.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(database)))


def owner(conn):
    identity = str(uuid.uuid4())
    conn.execute(f'INSERT INTO {snapshot.schema.OWNER} VALUES (1,%s,clock_timestamp()+interval \'60 seconds\')',
                 (identity,))
    conn.commit()
    return identity


def publish(conn, identity, value, signed, **changes):
    snapshot.publish_owned(conn, owner_id=identity, value=value, signature=signed,
        context_sha256=CONTEXT, subjects=changes.get('subjects', SUBJECTS), now=NOW)


def test_publication_and_read_do_not_commit_caller_state(conn):
    identity = owner(conn)
    value, signed = encode()
    publish(conn, identity, value, signed)
    assert snapshot.read_owned(conn, context_sha256=CONTEXT, now=NOW).panel == panel()
    conn.rollback()
    with pytest.raises(snapshot.SnapshotUnavailable, match='MISSING'):
        snapshot.read_owned(conn, context_sha256=CONTEXT, now=NOW)
    conn.rollback()
    publish(conn, identity, value, signed)
    conn.commit()
    with psycopg.connect(conn.info.dsn) as other:
        restored = snapshot.read_owned(other, context_sha256=CONTEXT, now=NOW+timedelta(seconds=1))
        assert restored.panel == panel()
    # A read cannot rewrite observation or expiry metadata.
    assert conn.execute(f'SELECT observed_at,valid_until FROM {snapshot.schema.RECEIPTS}').fetchone() == (
        NOW, NOW+timedelta(seconds=20))


def test_replaced_owner_and_changed_subject_cannot_publish(conn):
    identity = owner(conn)
    value, signed = encode()
    with pytest.raises(snapshot.SnapshotUnavailable, match='SUBJECT'):
        publish(conn, identity, value, signed, subjects={**SUBJECTS, 'PAPER': 'd'*64})
    with pytest.raises(snapshot.SnapshotUnavailable, match='OWNER'):
        publish(conn, str(uuid.uuid4()), value, signed)
    assert conn.execute(f'SELECT count(*) FROM {snapshot.schema.RECEIPTS}').fetchone() == (0,)


def test_removed_owner_guard_is_detected(conn, monkeypatch):
    code = inspect.getsource(snapshot.publish_owned)
    guard = "_require(owner is not None, 'SNAPSHOT_OWNER_LOST')"
    assert guard in code
    namespace = {}
    exec(compile(code.replace(guard, 'pass'), '<removed-snapshot-owner>', 'exec'), vars(snapshot), namespace)
    monkeypatch.setattr(snapshot, 'publish_owned', namespace['publish_owned'])
    with pytest.raises(pytest.fail.Exception):
        test_replaced_owner_and_changed_subject_cannot_publish(conn)


def test_database_metadata_tampering_is_rejected(conn):
    identity = owner(conn)
    value, signed = encode()
    publish(conn, identity, value, signed)
    conn.execute(f'UPDATE {snapshot.schema.RECEIPTS} SET valid_until=valid_until+interval \'1 second\'')
    with pytest.raises(snapshot.SnapshotUnavailable, match='METADATA'):
        snapshot.read_owned(conn, context_sha256=CONTEXT, now=NOW)


def test_same_native_subject_receipt_replacement_invalidates_only_its_scope(conn, monkeypatch):
    monkeypatch.setattr(snapshot.schema, 'require_schema', lambda *_: True)
    monkeypatch.setattr(snapshot.read_projection, '_subject_facts', lambda *_: ())
    monkeypatch.setattr(snapshot.read_projection, '_subject',
                        lambda _c, _d, scope, **_: SUBJECTS[scope])
    initial = snapshot.subjects(conn, conn.info.dsn)
    conn.execute(f'INSERT INTO {snapshot.schema.RECEIPTS} VALUES (%s,%s,%s,%s,%s,%s)',
        ('PAPER', SUBJECTS['PAPER'], NOW, NOW+timedelta(seconds=20),
         psycopg.types.json.Jsonb({'negative': False}), 'original-signature'))
    conn.commit()
    positive = snapshot.subjects(conn, conn.info.dsn)
    assert positive['SHADOW'] == initial['SHADOW'] and positive['PAPER'] != initial['PAPER']
    conn.execute(f'UPDATE {snapshot.schema.RECEIPTS} SET signature=%s WHERE scope=%s',
                 ('negative-signature', 'PAPER'))
    conn.commit()
    negative = snapshot.subjects(conn, conn.info.dsn)
    assert negative['SHADOW'] == positive['SHADOW'] and negative['PAPER'] != positive['PAPER']
    # Even a tamper retaining the claimed signature changes its physical version.
    conn.execute(f'UPDATE {snapshot.schema.RECEIPTS} SET envelope=%s WHERE scope=%s',
                 (psycopg.types.json.Jsonb({'tampered': True}), 'PAPER'))
    conn.commit()
    changed = snapshot.subjects(conn, conn.info.dsn)
    assert changed['SHADOW'] == negative['SHADOW'] and changed['PAPER'] != negative['PAPER']


def test_exact_read_lock_serializes_acknowledgement_against_snapshot_publication(conn):
    identity = owner(conn)
    value, signed = encode()
    publish(conn, identity, value, signed)
    conn.commit()
    snapshot.read_owned(conn, context_sha256=CONTEXT, now=NOW, lock=True)
    with psycopg.connect(conn.info.dsn) as other:
        other.execute("SET LOCAL lock_timeout='50ms'")
        with pytest.raises(psycopg.errors.LockNotAvailable):
            publish(other, identity, value, signed)
        other.rollback()
        conn.rollback()
        publish(other, identity, value, signed)


def test_context_binds_current_physical_database_runtime_and_account(conn, monkeypatch):
    from sentinel import schema
    for statement in schema.DDL:
        if statement.startswith('CREATE TABLE IF NOT EXISTS sentinel_account_binding ('):
            conn.execute(statement)
    conn.execute("INSERT INTO sentinel_account_binding(deployment_id,broker,broker_account_id,ownership_state) "
                 "VALUES ('private','alpaca','paper-one','SENTINEL_OWNED')")
    monkeypatch.setenv('ALPACA_BASE_URL', 'https://paper-api.alpaca.markets')
    baseline = snapshot.context(conn, conn.info.dsn)
    assert len(baseline) == 64 and snapshot.context(conn, conn.info.dsn) == baseline
    monkeypatch.setenv('SENTINEL_GIT_COMMIT', '1'*40)
    runtime = snapshot.context(conn, conn.info.dsn)
    assert runtime != baseline
    conn.execute("UPDATE sentinel_account_binding SET broker_account_id='paper-two'")
    assert snapshot.context(conn, conn.info.dsn) != runtime
