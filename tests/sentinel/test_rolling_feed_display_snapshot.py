"""Display metadata keeps a coherent MVCC frame; financial corpus pins remain."""
from contextlib import contextmanager
import inspect
from types import SimpleNamespace

import pytest

from sentinel.feed import operational_snapshot as op,publication,readers,readiness,rolling_store,store
from tests.sentinel.test_operational_snapshot import (  # noqa: F401
    conn,pg,source,operational_source,enqueue,
)

@pytest.fixture(scope='module',autouse=True)
def actual_private_wal_archiving(pg):
    pg.enable_archive()

def cache(conn,pub,*,negative=False):
    measured=readiness.Readiness()
    measured.add('private measured check',readiness.FAIL if negative else readiness.PASS,'fixture')
    readiness.save_snapshot(conn,readers.bound_readiness(pub,measured))
    snapshot=readiness.latest_snapshot(conn);conn.rollback()
    return snapshot

@pytest.fixture
def published(conn,operational_source,monkeypatch,tmp_path):
    from sentinel import backup_runtime_authority
    from sentinel.feed import rolling_publisher
    # Synthetic DATA_ONLY publication setup has no deployed external-media
    # authority. This fixture does not qualify or alter production durability.
    monkeypatch.setattr(backup_runtime_authority,'POLICY_MARKER',tmp_path/'no-deployed-backup-policy')
    monkeypatch.setenv('SENTINEL_PUBLICATION_RECEIPT_KEY','private-display-metadata-'+'x'*64)
    monkeypatch.setattr(rolling_publisher.identity,'require_feed_producer_identity',lambda:dict(
        schema='sentinel.feed-producer/1',git_commit='a'*40,
        runtime_image_digest='sha256:'+'b'*64,image_source_revision='a'*40))
    op.prepare(conn,enqueue(conn))
    pub=readers.current(conn)
    measured=cache(conn,pub)
    return pub,measured

def test_real_writer_lock_blocks_financial_default_but_not_rolling_display(conn,published):
    pub,measured=published
    writer=store.connect(conn.info.dsn)
    writer.execute('SELECT pg_advisory_lock(%s)',(publication.CORPUS_LOCK_KEY,));writer.commit()
    try:
        with pytest.raises(publication.CorpusLockUnavailable):
            readers.status_snapshot(conn,include_publication=True)
        conn.rollback()
        frontier,snapshot,version=readers.display_status_snapshot(conn,include_publication=True)
        assert (frontier,version)==(pub.window_end,pub.version)
        assert snapshot.ready is True and snapshot.computed_at==measured.computed_at
        assert conn.execute("SELECT current_setting('transaction_isolation'),current_setting('transaction_read_only')").fetchone()==('repeatable read','on')
    finally:
        conn.rollback();writer.close()

def test_rolling_display_does_not_admit_an_expensive_readiness_assessment(conn,published,monkeypatch):
    def forbidden(*args,**kwargs):pytest.fail('display assessed mutable or financial inputs')
    monkeypatch.setattr(readers,'pinned',forbidden)
    monkeypatch.setattr(readers,'readiness',forbidden)
    monkeypatch.setattr(readers.rolling_go_inputs,'assessment',forbidden)
    monkeypatch.setattr(readers.store,'latest_visible_session',forbidden)
    assert readers.display_status_snapshot(conn)[1].ready
    conn.rollback()

@pytest.mark.parametrize('negative',[False,True])
def test_measured_verdict_and_clock_are_preserved(conn,published,negative):
    pub,_=published
    measured=cache(conn,pub,negative=negative)
    frontier,snapshot,version=readers.display_status_snapshot(conn,include_publication=True)
    assert (frontier,version)==(pub.window_end,pub.version)
    assert snapshot.ready is (not negative) and snapshot.computed_at==measured.computed_at
    assert snapshot.checks==measured.checks
    conn.rollback()

def test_mismatched_verdict_is_absent_instead_of_false_or_pass(conn,published):
    pub,_=published
    readiness.save_snapshot(conn,readiness.Readiness())
    assert readers.display_status_snapshot(conn,include_publication=True)==(pub.window_end,None,pub.version)
    conn.rollback()

def test_read_only_display_cannot_write_even_presentation_cache(conn,published):
    import psycopg
    readers.display_status_snapshot(conn)
    with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
        conn.execute('DELETE FROM sentinel_readiness_snapshots')
    conn.rollback()

def test_autocommit_cannot_silently_drop_the_repeatable_snapshot(conn,published):
    conn.autocommit=True
    try:
        with pytest.raises(ValueError,match='CALLER_TRANSACTION'):
            readers.display_status_snapshot(conn)
    finally:conn.autocommit=False

def test_existing_queried_transaction_refuses_instead_of_mixing_frames(conn,published):
    import psycopg
    conn.execute('SELECT 1')
    with pytest.raises(psycopg.errors.ActiveSqlTransaction):
        readers.display_status_snapshot(conn)
    conn.rollback()

def test_existing_operational_binding_guard_still_rejects_bad_evidence(conn,published,monkeypatch):
    pub,_=published;target=pub.evidence['rolling_snapshot']['validation_sha256']
    original=rolling_store.load_evidence
    def corrupted(actual,key):
        proof=original(actual,key)
        return {**proof,'request_sha256':'f'*64} if key==target else proof
    monkeypatch.setattr(rolling_store,'load_evidence',corrupted)
    with pytest.raises(op.OperationalSnapshotRefused,match='OPERATIONAL_PROOF_MISMATCH'):
        readers.display_status_snapshot(conn)
    conn.rollback()


def test_invalid_publication_authentication_still_refuses_display(conn,published,monkeypatch):
    monkeypatch.setenv('SENTINEL_PUBLICATION_RECEIPT_KEY','different-private-display-key-'+'z'*64)
    with pytest.raises(publication.CorpusIncoherent):
        readers.display_status_snapshot(conn)
    conn.rollback()


def test_panel_helper_ends_its_prior_read_and_its_display_transaction(conn,published):
    from psycopg.pq import TransactionStatus
    from sentinel.panel.sources import _feed_status_snapshot
    pub,measured=published
    conn.execute('SELECT 1')
    frontier,snapshot,version=_feed_status_snapshot(conn)
    assert (frontier,version)==(pub.window_end,pub.version)
    assert snapshot.computed_at==measured.computed_at
    assert conn.info.transaction_status==TransactionStatus.IDLE

def assert_one_frame_across_peer_publication(conn,published,operational_source,monkeypatch):
    old,measured=published;peer=store.connect(conn.info.dsn)
    original=readiness.latest_snapshot;committed=[]
    def advance(actual):
        if actual is conn and not committed:
            committed.append(True)
            for row in operational_source['SEP']:
                if row['ticker']=='AAA':row['open']='50'
            op.prepare(peer,enqueue(peer,dependencies='next-display-generation'))
            new=readers.current(peer);assert new.version>old.version
            cache(peer,new)
        return original(actual)
    monkeypatch.setattr(readers.legacy_readiness,'latest_snapshot',advance)
    try:
        frontier,snapshot,version=readers.display_status_snapshot(conn,include_publication=True)
        assert committed and version==old.version and frontier==old.window_end
        assert snapshot is not None and snapshot.computed_at==measured.computed_at
        conn.rollback()
        assert readers.display_status_snapshot(conn,include_publication=True)[2]>version
    finally:conn.rollback();peer.close()

def test_peer_commit_cannot_mix_publication_and_cached_verdict(conn,published,operational_source,monkeypatch):
    assert_one_frame_across_peer_publication(conn,published,operational_source,monkeypatch)

def test_removing_repeatable_read_has_an_executed_peer_commit_falsifier(conn,published,operational_source,monkeypatch):
    raw=inspect.getsource(readers.display_status_snapshot)
    before='SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY'
    assert raw.count(before)==1
    namespace={}
    exec(compile(raw.replace(before,'SET TRANSACTION ISOLATION LEVEL READ COMMITTED READ ONLY'),
        'removed-display-snapshot-isolation','exec'),vars(readers),namespace)
    monkeypatch.setattr(readers,'display_status_snapshot',namespace['display_status_snapshot'])
    with pytest.raises(rolling_store.SnapshotStorageRefused,match='READ_ONLY_SNAPSHOT'):
        readers.display_status_snapshot(conn)
    conn.rollback()
    # Break the independent manifest guard too to expose the actual mixed frame.
    raw=inspect.getsource(rolling_store.display_manifest)
    namespace={}
    assert raw.count("('repeatable read', 'on')")==1
    exec(compile(raw.replace("('repeatable read', 'on')","('read committed', 'on')"),
        'removed-manifest-snapshot-guard','exec'),vars(rolling_store),namespace)
    monkeypatch.setattr(rolling_store,'display_manifest',namespace['display_manifest'])
    with pytest.raises(AssertionError):
        assert_one_frame_across_peer_publication(conn,published,operational_source,monkeypatch)

def test_legacy_display_still_takes_original_pin(conn,monkeypatch):
    pub=SimpleNamespace(window_end='2026-11-05',version=1)
    monkeypatch.setattr(readers,'_display_current',lambda actual:pub)
    monkeypatch.setattr(readers,'current',lambda actual:pub)
    monkeypatch.setattr(readers,'is_rolling',lambda actual:False)
    @contextmanager
    def refused(*args,**kwargs):
        raise publication.CorpusLockUnavailable('private legacy corpus writer')
        yield
    monkeypatch.setattr(readers,'pinned',refused)
    with pytest.raises(publication.CorpusLockUnavailable):readers.display_status_snapshot(conn)
    conn.rollback()


@pytest.mark.parametrize('setting',[
    'SET TRANSACTION ISOLATION LEVEL READ COMMITTED READ ONLY',
    'SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ WRITE',
])
def test_metadata_boundary_requires_both_snapshot_guards(conn,published,setting):
    pub,_=published
    conn.execute(setting)
    with pytest.raises(rolling_store.SnapshotStorageRefused,match='READ_ONLY_SNAPSHOT'):
        rolling_store.display_manifest(conn,pub.evidence['rolling_snapshot']['candidate_id'])
    conn.rollback()


def test_metadata_snapshot_guard_has_an_executed_falsifier(conn,published,monkeypatch):
    raw=inspect.getsource(rolling_store.display_manifest)
    needle="if settings != ('repeatable read', 'on'):"
    assert raw.count(needle)==1
    namespace={}
    exec(compile(raw.replace(needle,'if False:'),'removed-metadata-transaction-guard','exec'),
        vars(rolling_store),namespace)
    monkeypatch.setattr(rolling_store,'display_manifest',namespace['display_manifest'])
    with pytest.raises(pytest.fail.Exception):
        test_metadata_boundary_requires_both_snapshot_guards(conn,published,
            'SET TRANSACTION ISOLATION LEVEL READ COMMITTED READ ONLY')
    conn.rollback()
