"""Plan-only changes refresh presentation, not retained shadow history."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import inspect
from types import SimpleNamespace

import pytest
from psycopg.types.json import Jsonb

from sentinel.panel import model, read_projection as projection, sources
from sentinel.panel import shadow_execution_projection as execution
from tests.sentinel.test_operational_read_projection import conn, pg, install_projection, subjects

NOW = datetime(2031, 4, 21, 20, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def authentication(monkeypatch):
    monkeypatch.setenv('SENTINEL_PUBLICATION_RECEIPT_KEY', 'isolated-content-proof-' + 'x'*32)


def proof_rows(*, instant=NOW):
    rows = [model.Row(key,key,'verified',model.OK,as_of=instant,freshness=timedelta(seconds=600))
            for key in sorted(projection.SHADOW_KEYS)]
    book = model.ShadowBook(session=instant.date().isoformat(),cash='50000',receivables='0',nav='50000',
        pending_operations=0,holdings=[],slots=[model.ShadowSlot(slot_id=i,state='READY',cooldown_total=20)
                                              for i in range(20)])
    basis = model.ShadowProjectionBasis(session=book.session,observed_at=instant,
        target_core_exposure='0.65',slots_used=0,slots_total=20,nav='50000',cash='50000',
        blocked=False,unresolved=0,carried=0,pending=0)
    return [replace(row,shadow_book=book,shadow_projection=basis) if row.key=='book' else row for row in rows]


def test_plan_and_rollout_writes_do_not_invalidate_shadow_content(conn):
    install_projection(conn)
    before = subjects(conn)
    # A real statement trigger used to invalidate SHADOW even with no matching plan.
    conn.execute('UPDATE sentinel_execution_plans SET data_version=data_version WHERE false')
    conn.execute('UPDATE sentinel_rollout_state SET updated_at=clock_timestamp() WHERE id=1')
    conn.commit()
    after = subjects(conn)
    assert before[0] == after[0] and before[1] != after[1]


@pytest.mark.parametrize('mutation', ['insert','update','delete'])
def test_unknown_strategy_cursor_identity_mutations_still_invalidate(conn, mutation):
    install_projection(conn)
    conn.execute("INSERT INTO sentinel_processed_sessions VALUES ('unknown-strategy-input','2031-04-21','{}')")
    conn.commit()
    before = subjects(conn)
    if mutation == 'insert':
        conn.execute("INSERT INTO sentinel_processed_sessions VALUES ('another-unknown-input','2031-04-21','{}')")
    elif mutation == 'update':
        conn.execute("UPDATE sentinel_processed_sessions SET state='{}' WHERE cursor_name='unknown-strategy-input'")
    else:
        conn.execute("DELETE FROM sentinel_processed_sessions WHERE cursor_name='unknown-strategy-input'")
    conn.commit()
    after = subjects(conn)
    assert before[0] != after[0]


def test_current_plan_reprojection_keeps_original_proof_and_expiry(conn, monkeypatch):
    install_projection(conn)
    key = projection.subject(conn, conn.info.dsn, 'SHADOW')
    value, signature = projection.make('SHADOW',key,proof_rows(),[],observed_at=NOW)
    conn.execute('INSERT INTO sentinel_operational_verification_receipts VALUES (%s,%s,%s,%s,%s,%s)',
        ('SHADOW',key,NOW,NOW+timedelta(seconds=600),Jsonb(value),signature))
    conn.commit()
    selected = [None]
    reads = []
    def current(_conn):reads.append('plan');return selected[0]
    monkeypatch.setattr(sources,'_current_plan',current)
    monkeypatch.setattr(sources,'_rollout_state',lambda _c:dict(mode='PINNED_1_00',version=1,certificate_sha256=None))
    monkeypatch.setattr(sources,'_dual_authority_rows',lambda *a,**k:pytest.fail('consumer rescanned shadow history'))
    first = projection.read(conn.info.dsn,only_scope='SHADOW',now=NOW+timedelta(seconds=30))[0]
    selected[0] = dict(decision_session='2031-04-21',target_exposure=Decimal('1'),
        rollout_mode='PINNED_1_00',rollout_version=1,rollout_certificate_sha256=None,
        created_at=NOW+timedelta(seconds=40),unpriced_securities=[])
    second = projection.read(conn.info.dsn,only_scope='SHADOW',now=NOW+timedelta(seconds=50))[0]
    first_exposure = next(r for r in first if r.key=='exposure')
    second_exposure = next(r for r in second if r.key=='exposure')
    assert first_exposure.status == model.WARN and second_exposure.status == model.PENDING
    assert first_exposure.detail != second_exposure.detail
    assert second_exposure.valid_until == NOW+timedelta(seconds=600)
    book = next(r for r in second if r.key=='book')
    assert book.as_of == NOW and book.shadow_projection.observed_at == NOW
    assert [s.slot_id for s in book.shadow_book.slots] == list(range(20))
    assert reads == ['plan','plan']
    assert conn.execute('SELECT envelope,signature FROM sentinel_operational_verification_receipts WHERE scope=\'SHADOW\'').fetchone() == (value,signature)
    conn.rollback()
    expired = projection.read(conn.info.dsn,only_scope='SHADOW',now=NOW+timedelta(seconds=601))[0]
    assert all(row.status != model.OK for row in expired)
    assert reads == ['plan','plan']


def test_changed_rollout_cannot_reuse_old_plan_adoption(monkeypatch):
    plan = dict(decision_session='2031-04-21',target_exposure=Decimal('1'),rollout_mode='PINNED_1_00',
        rollout_version=1,rollout_certificate_sha256=None,created_at=NOW,unpriced_securities=[])
    monkeypatch.setattr(sources,'_current_plan',lambda _:plan)
    monkeypatch.setattr(sources,'_rollout_state',lambda _:dict(mode='PINNED_1_00',version=2,certificate_sha256=None))
    with pytest.raises(ValueError,match='rollout authority disagree'):
        execution.project(None,proof_rows(),observed_at=NOW,valid_until=NOW+timedelta(seconds=600),now=NOW)


@pytest.mark.parametrize('defect', [None, 'no_wait', 'wrong_certificate',
    'missing_predecessor', 'different_mode', 'different_exposure'])
def test_fee_wait_withdraws_only_adoption_and_retains_authenticated_shadow(conn, monkeypatch, defect):
    from sentinel import activation_fee_wait
    from sentinel.feed import calendar

    install_projection(conn)
    prior, successor = 'a'*64, 'b'*64
    session = NOW.date().isoformat()
    for version, start, end, certificate in (
            (2, 'PINNED_1_00', 'CONTROLLER', prior),
            (3, 'CONTROLLER', 'CONTROLLER', successor)):
        if defect == 'missing_predecessor' and version == 2:
            continue
        conn.execute('INSERT INTO sentinel_rollout_events '
            '(version,from_mode,to_mode,certificate_sha256,reason) VALUES (%s,%s,%s,%s,%s)',
            (version, 'PINNED_1_00' if defect == 'different_mode' and version == 3 else start,
             end, certificate, 'fixture'))
    key = projection.subject(conn, conn.info.dsn, 'SHADOW')
    expiry = NOW+timedelta(seconds=600)
    value, signature = projection.make('SHADOW',key,proof_rows(),[],observed_at=NOW)
    conn.execute('INSERT INTO sentinel_operational_verification_receipts VALUES (%s,%s,%s,%s,%s,%s)',
        ('SHADOW',key,NOW,expiry,Jsonb(value),signature))
    conn.commit()
    plan = dict(plan_id='prior', decision_session=session, effective_session=calendar.next_session(session),
        target_exposure=Decimal('0.60' if defect == 'different_exposure' else '0.65'),
        rollout_mode='CONTROLLER', rollout_version=2, rollout_certificate_sha256=prior)
    monkeypatch.setattr(sources,'_current_plan',lambda _:plan)
    monkeypatch.setattr(sources,'_rollout_state',lambda _:dict(mode='CONTROLLER',version=3,
        certificate_sha256=successor))
    wait = SimpleNamespace(decision_session=NOW.date(),valid_until=NOW+timedelta(seconds=90),
        certificate_sha256=('c'*64 if defect == 'wrong_certificate' else successor))
    monkeypatch.setattr(activation_fee_wait,'read_owned',lambda *_a,**_k: None if defect == 'no_wait' else wait)
    instant = NOW+timedelta(seconds=30)
    result, _, _, errors, scoped = projection.read(conn.info.dsn,only_scope='SHADOW',now=instant,with_error_scopes=True)
    rows = {row.key: row for row in result}
    signed, _, _, _ = projection.decode(value,signature,current_subject=key,scope='SHADOW',now=instant)
    assert all(rows[row.key] == row for row in signed if row.key != 'exposure')
    assert rows['exposure'].status == model.UNKNOWN
    if defect is None:
        assert not errors
        assert rows['exposure'].valid_until == wait.valid_until
        assert rows['exposure'].operational_fact.state == 'ROLLOUT_RENEWAL_PENDING'
    else:
        assert errors == scoped['SHADOW'] == ['current plan adoption: current plan and rollout authority disagree']
        assert rows['exposure'].value == 'CURRENT PLAN NOT ADOPTED'
        assert rows['exposure'].effective_status(instant) == model.UNKNOWN
        assert rows['exposure'].valid_until == expiry
        assert rows['exposure'].operational_fact is None
    if defect == 'no_wait':
        plan.update(rollout_version=3,rollout_certificate_sha256=successor,created_at=instant,unpriced_securities=[])
        adopted, _, _, errors = projection.read(conn.info.dsn,only_scope='SHADOW',now=instant+timedelta(seconds=1))
        assert not errors
        exposure = next(row for row in adopted if row.key == 'exposure')
        assert exposure.operational_fact.state == 'ADOPTED' and exposure.valid_until == expiry


@pytest.mark.parametrize('defect', ['signature','old_subject','expiry','book_basis'])
def test_rollout_mismatch_cannot_rescue_an_unproved_shadow_receipt(conn, monkeypatch, defect):
    install_projection(conn)
    key = projection.subject(conn, conn.info.dsn, 'SHADOW')
    if defect == 'old_subject':
        key = '0'*64
    rows = proof_rows()
    if defect == 'book_basis':
        rows = [replace(row, shadow_projection=None) if row.key=='book' else row for row in rows]
    value, signature = projection.make('SHADOW',key,rows,[],observed_at=NOW)
    expiry = NOW+timedelta(seconds=600)
    conn.execute('INSERT INTO sentinel_operational_verification_receipts VALUES (%s,%s,%s,%s,%s,%s)',
        ('SHADOW',key,NOW,expiry,Jsonb(value),'0'*64 if defect=='signature' else signature))
    conn.commit()
    monkeypatch.setattr(sources, '_current_plan', lambda _:pytest.fail('unproved receipt consulted current plan'))
    instant = expiry+timedelta(microseconds=1) if defect=='expiry' else NOW
    result, _, _, errors = projection.read(conn.info.dsn,only_scope='SHADOW',now=instant)
    assert errors and all(row.status != model.OK for row in result)
    assert all(row.operational_fact is None for row in result)


def test_wrong_fee_certificate_falsifies_removed_binding_guard(conn, monkeypatch):
    source = inspect.getsource(projection._activation_renewal_exposure)
    binding = 'or current_certificate != wait.certificate_sha256'
    assert source.count(binding) == 1
    namespace = {}
    exec(compile(source.replace(binding, ''), '<removed wait certificate binding>', 'exec'),
         projection.__dict__, namespace)
    monkeypatch.setattr(projection, '_activation_renewal_exposure', namespace['_activation_renewal_exposure'])
    with pytest.raises(AssertionError):
        test_fee_wait_withdraws_only_adoption_and_retains_authenticated_shadow(conn, monkeypatch, 'wrong_certificate')


@pytest.mark.parametrize('defect', [None, 'released', 'expired', 'other_image', 'negative_verdict'])
def test_only_exact_fenced_lifecycle_can_explain_an_unwritten_runtime_verdict(monkeypatch, defect):
    from sentinel import local_paper

    commit, image = 'b'*40, 'sha256:'+'a'*64
    monkeypatch.setattr(local_paper, 'enabled', lambda: True)
    monkeypatch.setenv('SENTINEL_GIT_COMMIT', commit)
    monkeypatch.setenv('SENTINEL_RUNTIME_IMAGE_DIGEST', image)
    control = dict(enabled=False,killed=defect != 'released',certificate_sha256='c'*64)
    lifecycle = dict(lifecycle_status='ACTIVE',lifecycle_current=defect != 'expired',
        certificate_sha256='c'*64,reviewed_git_commit=commit,
        reviewed_image_digest='sha256:'+'d'*64 if defect == 'other_image' else image)
    row = sources._execution_authority_display(lifecycle, control,
        verdict='FAIL' if defect == 'negative_verdict' else None, detail=None, checked_at=None)
    assert row.status in {model.FAIL,model.UNKNOWN}
    assert (row.operational_fact is not None) is (defect is None)
    if defect is None:
        assert row.operational_fact.state == 'ACTIVATION_VERDICT_WITHDRAWN'


def test_removed_plan_coherence_guard_is_detected(monkeypatch):
    source = inspect.getsource(sources._exposure_row)
    needle = 'if plan_rollout != current_rollout:'
    assert source.count(needle) == 1
    namespace = {}
    exec(compile(source.replace(needle,'if False:'),'removed rollout display guard','exec'),sources.__dict__,namespace)
    monkeypatch.setattr(sources,'_exposure_row',namespace['_exposure_row'])
    with pytest.raises(pytest.fail.Exception):
        test_changed_rollout_cannot_reuse_old_plan_adoption(monkeypatch)
