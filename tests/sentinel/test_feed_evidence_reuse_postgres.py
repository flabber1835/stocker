"""Real byte-query counts and tuple/DDL invalidation in private PostgreSQL."""
import inspect
import uuid

import psycopg
from psycopg import sql
import pytest

from sentinel import operational_ddl_epoch
from sentinel.feed import rolling_store
from sentinel.panel import feed_display as display
from tests.sentinel.test_rolling_snapshot_publisher import pg  # noqa: F401


@pytest.fixture
def evidence_db(pg):
    database='byte_proof_'+uuid.uuid4().hex
    with psycopg.connect(pg.sync_dsn,autocommit=True) as admin:
        admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(database)))
    conn=psycopg.connect(pg.sync_dsn.rsplit('/',1)[0]+'/'+database)
    # This fixture qualifies display integrity, not a financial schema/book.
    conn.execute('CREATE TABLE sentinel_snapshot_evidence '
        '(evidence_sha256 text PRIMARY KEY,payload jsonb,canonical_payload text)')
    conn.commit()
    display._BYTE_PROOFS.clear()
    try:yield conn
    finally:
        display._BYTE_PROOFS.clear()
        conn.close()
        with psycopg.connect(pg.sync_dsn,autocommit=True) as admin:
            admin.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(database)))


class Measured:
    def __init__(self,conn):self.conn=conn;self.hash_queries=0
    @property
    def info(self):return self.conn.info
    def execute(self,statement,params=()):
        if "sha256(convert_to(canonical_payload,'UTF8'))" in str(statement):
            self.hash_queries+=1
        return self.conn.execute(statement,params)


def install(conn):
    for statement in operational_ddl_epoch.DDL:conn.execute(statement)
    conn.commit()


def seed(conn):
    from sentinel.feed.rolling_contract import canonical_json,digest
    value={'test_only_reference':'private immutable evidence'}
    identity=digest(value)
    conn.execute('INSERT INTO sentinel_snapshot_evidence VALUES (%s,NULL,%s)',
        (identity,canonical_json(value)))
    conn.commit()
    return identity


def frame(measured,identity):
    measured.conn.execute('BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
    try:
        context=display._byte_context(measured)
        display._verify_evidence(measured,identity,context=context)
        return context
    finally:measured.conn.rollback()


def test_unchanged_real_tuple_earns_one_actual_hash_query(evidence_db):
    install(evidence_db);identity=seed(evidence_db);measured=Measured(evidence_db)
    first=frame(measured,identity)
    assert first is not None and frame(measured,identity)==first
    assert measured.hash_queries==1 and len(display._BYTE_PROOFS)==1


def test_absent_real_ddl_witness_always_runs_canonical_verifier(evidence_db):
    identity=seed(evidence_db);measured=Measured(evidence_db)
    assert frame(measured,identity) is None and frame(measured,identity) is None
    assert measured.hash_queries==2 and not display._BYTE_PROOFS


def test_real_same_length_corruption_cannot_reuse_success(evidence_db):
    install(evidence_db);identity=seed(evidence_db);measured=Measured(evidence_db)
    frame(measured,identity)
    evidence_db.execute("UPDATE sentinel_snapshot_evidence SET canonical_payload="
        "replace(canonical_payload,'private','corrupt') WHERE evidence_sha256=%s",(identity,))
    evidence_db.commit()
    with pytest.raises(rolling_store.SnapshotStorageRefused,match='corrupt'):
        frame(measured,identity)
    assert measured.hash_queries==2


def test_real_noop_tuple_write_still_requires_fresh_hash(evidence_db):
    install(evidence_db);identity=seed(evidence_db);measured=Measured(evidence_db)
    frame(measured,identity)
    evidence_db.execute('UPDATE sentinel_snapshot_evidence SET canonical_payload=canonical_payload '
        'WHERE evidence_sha256=%s',(identity,));evidence_db.commit()
    frame(measured,identity)
    assert measured.hash_queries==2


def test_real_ddl_change_invalidates_unchanged_bytes(evidence_db):
    install(evidence_db);identity=seed(evidence_db);measured=Measured(evidence_db)
    first=frame(measured,identity)
    evidence_db.execute('ALTER TABLE sentinel_snapshot_evidence ADD private_test_note text')
    evidence_db.commit()
    assert frame(measured,identity)!=first and measured.hash_queries==2


def test_real_missing_evidence_refuses_even_after_success(evidence_db):
    install(evidence_db);identity=seed(evidence_db);measured=Measured(evidence_db)
    frame(measured,identity)
    evidence_db.execute('DELETE FROM sentinel_snapshot_evidence WHERE evidence_sha256=%s',(identity,))
    evidence_db.commit()
    with pytest.raises(rolling_store.SnapshotStorageRefused,match='missing'):
        frame(measured,identity)
    assert measured.hash_queries==2


def test_removed_real_tuple_subject_has_an_executed_falsifier(evidence_db,monkeypatch):
    source=inspect.getsource(display._byte_subject)
    assert source.count('list(row)')==1
    values={}
    exec(compile(source.replace('list(row)','[]'),'removed-real-tuple-subject','exec'),vars(display),values)
    monkeypatch.setattr(display,'_byte_subject',values['_byte_subject'])
    with pytest.raises(pytest.fail.Exception):
        test_real_same_length_corruption_cannot_reuse_success(evidence_db)
