"""Real published data can gain a DATA_ONLY strategy receipt without reacquisition.

The named historical FormationWindow fixture supplies 25 synthetic securities
as data only. These tests make no canonical-book, deployment or execution claim.
The private database uses explicit local PAPER account/artifact inputs; its real
backup-policy and feed-producer validators remain installed.
"""
from dataclasses import replace
import inspect

import pytest

from sentinel import binding, identity, local_paper, schema
from sentinel.feed import generation_admission as admission, rolling_go_inputs as inputs
from sentinel.feed import rolling_jobs, operational_snapshot as snapshots, publication
from sentinel.feed import readiness_scope, store
from sentinel.feed.rolling_contract import digest
from tests.sentinel.test_rolling_go_inputs import issuer_source, published  # noqa: F401
from tests.sentinel.test_rolling_initialization import ready  # noqa: F401
from tests.sentinel.test_operational_snapshot import operational_source  # noqa: F401
from tests.sentinel.test_rolling_snapshot_publisher import conn as snapshot_conn, pg, source  # noqa: F401

TARGET = '2026-09-14'
ACCOUNT = 'PAISOLATEDGENERATION'
_REAL_FEED_PRODUCER = identity.require_feed_producer_identity


@pytest.fixture
def conn(snapshot_conn,source,monkeypatch):
    """Install the actual selected PAPER profile before the retained data fixture."""
    commit='a'*40;image='sha256:'+'b'*64
    values={
        local_paper.MODE_ENV:local_paper.MODE,local_paper.ACCOUNT_ENV:ACCOUNT,
        'ALPACA_BASE_URL':'https://paper-api.alpaca.markets',
        'SENTINEL_GIT_COMMIT':commit,'SENTINEL_IMAGE_SOURCE_REVISION':commit,
        'SENTINEL_RUNTIME_IMAGE_DIGEST':image,'SENTINEL_TEST_IMAGE_DIGEST':image,
        'SENTINEL_FEED_GIT_COMMIT':commit,'SENTINEL_FEED_RUNTIME_IMAGE_DIGEST':image,
        'SENTINEL_FEED_AUTHORIZED':identity.FEED_AUTHORIZATION_VALUE,
        'SENTINEL_PUBLICATION_RECEIPT_KEY':'isolated-data-generation-key-'*4,
        'SENTINEL_PAPER_BUY_POLICY':'PROTECTED_LIMIT_DAY_V1',
        'SENTINEL_PAPER_BUY_CAP_BPS':'100',
    }
    for name,value in values.items(): monkeypatch.setenv(name,value)
    monkeypatch.delenv('SENTINEL_FEED_SERVICE_MODE',raising=False)
    # The old source fixture substitutes this issuer. Restore the real guard
    # and provide its explicit private artifact inputs instead.
    monkeypatch.setattr(identity,'require_feed_producer_identity',_REAL_FEED_PRODUCER)
    schema.ensure_schema(snapshot_conn)
    binding.bind(snapshot_conn,deployment_id='isolated-data-generation',broker='alpaca',
        broker_account_id=ACCOUNT)
    snapshot_conn.commit()
    assert local_paper.require_bound_account(snapshot_conn)
    snapshot_conn.rollback()
    assert identity.require_feed_producer_identity()['git_commit']==commit
    return snapshot_conn


def next_strategy(monkeypatch):
    controller,selected = inputs.production_strategy()
    changed = {**selected,'data_semantics_source_sha256':'9'*64}
    assert changed != selected
    monkeypatch.setattr(inputs,'production_strategy',lambda:(controller,changed))
    return selected,changed


def test_same_authenticated_inputs_are_admitted_without_provider_or_job_mutation(conn,published,issuer_source,monkeypatch):
    before = conn.execute('SELECT to_jsonb(j) FROM sentinel_snapshot_jobs j WHERE job_id=%s',
                          (published['job_id'],)).fetchone()[0]
    observed = list(issuer_source['calls'])
    original,selected = next_strategy(monkeypatch)
    conn.commit()
    monkeypatch.setattr(snapshots,'enqueue',lambda *_a,**_k:pytest.fail('existing data reacquired'))
    result = inputs.prepare(conn,target_session=TARGET)
    assert result['status'] == 'ALREADY_CURRENT'
    assert result['snapshot_id'] == published['snapshot_id']
    assert issuer_source['calls'] == observed
    assert conn.execute('SELECT to_jsonb(j) FROM sentinel_snapshot_jobs j WHERE job_id=%s',
                        (published['job_id'],)).fetchone()[0] == before
    assert conn.execute('SELECT COUNT(*) FROM sentinel_snapshot_jobs').fetchone()[0] == 1
    assert conn.execute('SELECT COUNT(*) FROM sentinel_corpus_publications').fetchone()[0] == 1
    receipt = conn.execute(f'SELECT receipt FROM {admission.TABLE}').fetchone()[0]
    assert receipt['scope'] == 'DATA_ONLY' and receipt['operational_go'] is False
    assert receipt['strategy_sha256'] == digest(selected) != digest(original)
    assert receipt['generation']['snapshot_id'] == published['snapshot_id']
    conn.commit()
    inputs.require_schemas(conn)
    with inputs.pinned(conn) as pub:
        assert admission.admitted(conn,pub,selected)
        assert inputs.validate_status(conn,pub)[1].ready
    conn.rollback()
    assert inputs.prepare(conn,target_session=TARGET)['status'] == 'ALREADY_CURRENT'
    assert conn.execute(f'SELECT COUNT(*) FROM {admission.TABLE}').fetchone()[0] == 1


def test_changed_strategy_cannot_read_without_a_current_authenticated_receipt(conn,published,monkeypatch):
    next_strategy(monkeypatch)
    conn.commit()
    inputs.require_schemas(conn)
    with inputs.pinned(conn) as pub:
        with pytest.raises(inputs.RollingGoRefused,match='STRATEGY_ADMISSION_REQUIRED'):
            inputs.validate_status(conn,pub)


def test_admission_cannot_preseal_an_unselected_strategy(conn,published):
    _,selected=inputs.production_strategy()
    unselected={**selected,'data_semantics_source_sha256':'7'*64}
    assert digest(unselected)!=digest(selected)
    with inputs.pinned(conn) as pub:
        with pytest.raises(admission.GenerationRefused,match='STRATEGY_NOT_CURRENT'):
            admission.admit_current(conn,pub,strategy=unselected,target=TARGET)
        assert conn.execute(f'SELECT COUNT(*) FROM {admission.TABLE}').fetchone()[0]==0


def test_removed_current_strategy_guard_is_killed_by_unselected_receipt_regression(conn,published,monkeypatch):
    monkeypatch.setattr(admission,'_require_current_strategy',lambda _strategy:None)
    with pytest.raises(pytest.fail.Exception,match='DID NOT RAISE'):
        test_admission_cannot_preseal_an_unselected_strategy(conn,published)


def test_admission_rechecks_selected_strategy_before_inserting_receipt(conn,published,monkeypatch):
    controller,selected=inputs.production_strategy()
    changed={**selected,'data_semantics_source_sha256':'8'*64}
    assert digest(changed)!=digest(selected)
    generation=admission.generation
    def change_selection(database,pub):
        value=generation(database,pub)
        monkeypatch.setattr(inputs,'production_strategy',lambda:(controller,changed))
        return value
    monkeypatch.setattr(admission,'generation',change_selection)
    with inputs.pinned(conn) as pub:
        with pytest.raises(admission.GenerationRefused,match='STRATEGY_NOT_CURRENT'):
            admission.admit_current(conn,pub,strategy=selected,target=TARGET)
        assert conn.execute(f'SELECT COUNT(*) FROM {admission.TABLE}').fetchone()[0]==0


def test_removed_final_strategy_check_is_killed_by_mid_assessment_selection_change(conn,published,monkeypatch):
    source=inspect.getsource(admission.admit_current)
    needle='    _require_current_strategy(strategy)\n'
    assert source.count(needle)==2
    before,after=source.rsplit(needle,1)
    namespace={}
    exec(compile(before+after,'removed-admission-final-strategy','exec'),vars(admission),namespace)
    monkeypatch.setattr(admission,'admit_current',namespace['admit_current'])
    with pytest.raises(pytest.fail.Exception,match='DID NOT RAISE'):
        test_admission_rechecks_selected_strategy_before_inserting_receipt(conn,published,monkeypatch)


def test_admission_requires_the_original_live_publication_pin(conn,published):
    pub = inputs.current(conn)
    _,selected = inputs.production_strategy()
    with pytest.raises(publication.CorpusIncoherent,match='OWNED_PUBLICATION_PIN_REQUIRED'):
        admission.admit_current(conn,pub,strategy=selected,target=TARGET)
    assert conn.execute(f'SELECT COUNT(*) FROM {admission.TABLE}').fetchone()[0] == 0


@pytest.mark.parametrize('damage',['lost-pin','foreign-connection','changed-publication'])
def test_admission_rejects_a_lost_or_different_original_pin(conn,published,damage):
    _,selected=inputs.production_strategy()
    other=None
    with inputs.pinned(conn) as pub:
        used=conn;subject=pub
        if damage=='lost-pin':
            assert conn.execute('SELECT pg_advisory_unlock_shared(%s)',(publication.CORPUS_LOCK_KEY,)).fetchone()[0]
        elif damage=='foreign-connection':
            other=store.connect(conn.info.dsn);used=other
        else:
            subject=replace(pub,version=pub.version+1)
        try:
            with pytest.raises(publication.CorpusIncoherent,match='PIN_(REQUIRED|LOST)'):
                admission.admit_current(used,subject,strategy=selected,target=TARGET)
            assert conn.execute(f'SELECT COUNT(*) FROM {admission.TABLE}').fetchone()[0] == 0
        finally:
            if other is not None: other.close()


def test_admission_rechecks_original_pin_before_inserting_receipt(conn,published,monkeypatch):
    _,selected=inputs.production_strategy()
    generation=admission.generation;released=False
    def lose_pin(database,pub):
        nonlocal released
        value=generation(database,pub)
        if not released:
            assert database.execute('SELECT pg_advisory_unlock_shared(%s)',
                (publication.CORPUS_LOCK_KEY,)).fetchone()[0]
            # The read above also owns a transaction-level shared corpus pin.
            # End that read-only transaction to create an actual unprotected
            # interval before the final admission guard, rather than merely
            # transferring protection between overlapping lock owners.
            database.commit()
            key=publication.CORPUS_LOCK_KEY
            assert not database.execute(
                "SELECT EXISTS (SELECT 1 FROM pg_locks WHERE locktype='advisory' "
                "AND pid=pg_backend_pid() "
                "AND database=(SELECT oid FROM pg_database WHERE datname=current_database()) "
                "AND classid=%s AND objid=%s AND objsubid=1 AND mode='ShareLock' AND granted)",
                (key>>32,key&0xffffffff)).fetchone()[0], 'fixture did not release every corpus pin'
            released=True
        return value
    monkeypatch.setattr(admission,'generation',lose_pin)
    with inputs.pinned(conn) as pub:
        with pytest.raises(publication.CorpusIncoherent,match='PIN_LOST'):
            admission.admit_current(conn,pub,strategy=selected,target=TARGET)
        assert conn.execute(f'SELECT COUNT(*) FROM {admission.TABLE}').fetchone()[0] == 0, 'receipt inserted after pin loss'


def test_removed_required_pin_is_killed_by_unpinned_admission_regression(conn,published,monkeypatch):
    monkeypatch.setattr(readiness_scope,'require_owned_publication',lambda *_:None)
    with pytest.raises(pytest.fail.Exception,match='DID NOT RAISE'):
        test_admission_requires_the_original_live_publication_pin(conn,published)


def test_removed_final_pin_check_is_killed_by_mid_assessment_loss(conn,published,monkeypatch):
    source=inspect.getsource(admission.admit_current)
    needle='    readiness_scope.require_owned_publication(conn,pub)\n'
    assert source.count(needle)==2
    before,after=source.rsplit(needle,1)
    namespace={}
    exec(compile(before+after,'removed-admission-final-pin','exec'),vars(admission),namespace)
    monkeypatch.setattr(admission,'admit_current',namespace['admit_current'])
    with pytest.raises((pytest.fail.Exception,AssertionError),match='DID NOT RAISE|receipt inserted after pin loss'):
        test_admission_rechecks_original_pin_before_inserting_receipt(conn,published,monkeypatch)


def test_stale_data_never_receives_new_strategy_admission(conn,published,monkeypatch):
    _,selected = next_strategy(monkeypatch)
    conn.commit()
    inputs.require_schemas(conn)
    with inputs.pinned(conn) as pub:
        with pytest.raises(inputs.RollingSourceFrontierPending):
            admission.admit_current(conn,pub,strategy=selected,target='2026-09-15')
    assert conn.execute(f'SELECT COUNT(*) FROM {admission.TABLE}').fetchone()[0] == 0


@pytest.mark.parametrize('defect',['hmac','identity','payload'])
def test_corrupt_receipt_is_not_data_authority(conn,published,monkeypatch,defect):
    _,selected = next_strategy(monkeypatch)
    conn.commit()
    inputs.prepare(conn,target_session=TARGET)
    conn.execute('SET LOCAL session_replication_role=replica')
    if defect == 'hmac':
        conn.execute(f"UPDATE {admission.TABLE} SET hmac_sha256=%s",('0'*64,))
    elif defect == 'identity':
        conn.execute(f"UPDATE {admission.TABLE} SET generation_sha256=%s",('0'*64,))
    else:
        conn.execute(f"UPDATE {admission.TABLE} SET receipt=jsonb_set(receipt,'{{operational_go}}','true')")
    conn.commit()
    inputs.require_schemas(conn)
    with inputs.pinned(conn) as pub:
        with pytest.raises(admission.GenerationRefused,match='ADMISSION_CHANGED'):
            admission.admitted(conn,pub,selected)


def test_receipt_is_immutable_and_failed_attempt_rolls_back(conn,published,monkeypatch):
    _,selected = next_strategy(monkeypatch)
    conn.commit()
    inputs.prepare(conn,target_session=TARGET)
    with pytest.raises(Exception,match='immutable'):
        conn.execute(f'DELETE FROM {admission.TABLE}')
    conn.rollback()
    assert conn.execute(f'SELECT COUNT(*) FROM {admission.TABLE}').fetchone()[0] == 1


def test_signature_guard_falsifier_cannot_validate_changed_receipt(conn,published,monkeypatch):
    _,selected = next_strategy(monkeypatch)
    conn.commit()
    inputs.prepare(conn,target_session=TARGET)
    conn.execute('SET LOCAL session_replication_role=replica')
    conn.execute(f'UPDATE {admission.TABLE} SET hmac_sha256=%s',('0'*64,))
    conn.commit()
    inputs.require_schemas(conn)
    with inputs.pinned(conn) as pub:
        with pytest.raises(admission.GenerationRefused):
            admission.admitted(conn,pub,selected)
        monkeypatch.setattr(admission,'_signature',lambda _:'0'*64)
        with pytest.raises(pytest.fail.Exception,match='DID NOT RAISE'):
            with pytest.raises(admission.GenerationRefused):
                admission.admitted(conn,pub,selected)
