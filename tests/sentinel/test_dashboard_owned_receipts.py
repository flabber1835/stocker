"""Caller-owned financial receipt reads retain one committed database view."""
from datetime import datetime,timezone

import psycopg
import pytest

from sentinel.feed import store
from sentinel.panel import model,read_projection as receipts,review_store
from tests.sentinel.test_operational_projection_service import (
    operational,conn,pg,save_financial,  # noqa: F401
)


def test_owned_receipt_read_keeps_snapshot_across_a_concurrent_negative_commit(operational):
    c,_,_=operational
    save_financial(c,'PAPER')
    c.execute('BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
    before=c.execute('SELECT pg_current_snapshot()::text').fetchone()[0]
    first=receipts.read_owned(c,c.info.dsn,now=review_store.database_now(c),only_scope='PAPER')
    assert first[0][0].status==model.OK
    with psycopg.connect(c.info.dsn) as writer:
        save_financial(writer,'PAPER',[model.paper_reconciliation_row(state='MISMATCH')])
    again=receipts.read_owned(c,c.info.dsn,now=review_store.database_now(c),only_scope='PAPER')
    assert again==first
    assert c.execute('SELECT pg_current_snapshot()::text').fetchone()[0]==before
    assert c.execute('SHOW transaction_read_only').fetchone()==('on',)
    assert c.execute('SHOW transaction_isolation').fetchone()==('repeatable read',)
    c.rollback()
    c.execute('BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
    current=receipts.read_owned(c,c.info.dsn,now=review_store.database_now(c),only_scope='PAPER')
    assert current[0][0].status==model.FAIL
    assert not current[3]
    c.rollback()


def test_owned_read_never_connects_or_controls_the_borrowed_transaction(operational,monkeypatch):
    c,_,_=operational
    save_financial(c,'PAPER')
    c.execute('BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
    facts=receipts._subject_facts(c)
    def forbidden(*_args,**_kwargs):pytest.fail('owned receipt reader acquired another connection or fact set')
    monkeypatch.setattr(store,'connect',forbidden)
    monkeypatch.setattr(receipts,'_subject_facts',forbidden)
    statements=[]
    class Borrowed:
        def execute(self,sql,*args,**kwargs):
            statements.append(sql)
            assert sql.lstrip().upper().startswith('SELECT ')
            return c.execute(sql,*args,**kwargs)
        def __getattr__(self,key):
            assert key not in {'commit','rollback','close','transaction','set_autocommit','set_isolation_level'}
            return getattr(c,key)
    result=receipts.read_owned(Borrowed(),c.info.dsn,now=review_store.database_now(c),
                               only_scope='PAPER',facts=facts)
    assert result[0][0].status==model.OK and statements
    assert c.info.transaction_status==psycopg.pq.TransactionStatus.INTRANS
    # A real attempted write must still be refused after the borrowed read.
    with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
        with c.transaction():
            c.execute('UPDATE sentinel_automation_control SET generation=generation WHERE id=1')
    assert c.execute('SHOW transaction_isolation').fetchone()==('repeatable read',)
    c.rollback()


def test_connection_owning_compatibility_reader_uses_exactly_one_read_only_transaction(operational,monkeypatch):
    c,_,_=operational
    save_financial(c,'PAPER')
    original=store.connect;opened=[]
    def connected(*args,**kwargs):
        connection=original(*args,**kwargs);opened.append(connection);return connection
    monkeypatch.setattr(store,'connect',connected)
    owned=receipts.read_owned;seen=[]
    def inspect(connection,*args,**kwargs):
        seen.append(connection)
        assert connection.execute('SHOW transaction_read_only').fetchone()==('on',)
        assert connection.execute('SHOW transaction_isolation').fetchone()==('repeatable read',)
        return owned(connection,*args,**kwargs)
    monkeypatch.setattr(receipts,'read_owned',inspect)
    result=receipts.read(c.info.dsn,only_scope='PAPER',now=datetime.now(timezone.utc))
    assert result[0][0].status==model.OK
    assert len(opened)==1 and seen==opened and opened[0].closed


@pytest.mark.parametrize('scope',['PAPER','SHADOW'])
def test_supplied_revision_factor_preserves_exact_native_subject_without_reloading_revision(operational,scope):
    c,_,_=operational
    facts=receipts._subject_facts(c)
    row=c.execute(f'SELECT incarnation::text,revision,xmin::text FROM {receipts.schema.REVISION} '
                  'WHERE scope=%s',(scope,)).fetchone()
    expected=receipts._subject(c,c.info.dsn,scope,facts=facts)
    class ExistingRevision:
        def execute(self,sql,*args,**kwargs):
            assert 'SELECT incarnation::text,revision,xmin::text' not in sql
            return c.execute(sql,*args,**kwargs)
    assert receipts._subject_for_revision(ExistingRevision(),c.info.dsn,scope,row,facts=facts)==expected
    c.rollback()


def test_original_revision_recomputes_only_with_the_current_physical_and_configuration_basis(operational,monkeypatch):
    c,_,_=operational
    row=c.execute(f'SELECT incarnation::text,revision,xmin::text FROM {receipts.schema.REVISION} '
                  "WHERE scope='PAPER'").fetchone()
    before=receipts._subject(c,c.info.dsn,'PAPER')
    c.commit()
    c.execute('UPDATE sentinel_automation_control SET generation=generation+1 WHERE id=1')
    c.commit()
    facts=receipts._subject_facts(c)
    assert receipts._subject(c,c.info.dsn,'PAPER',facts=facts)!=before
    assert receipts._subject_for_revision(c,c.info.dsn,'PAPER',row,facts=facts)==before
    monkeypatch.setenv('SENTINEL_RUNTIME_IMAGE_DIGEST','sha256:'+'9'*64)
    current_facts=receipts._subject_facts(c)
    assert receipts._subject_for_revision(c,c.info.dsn,'PAPER',row,facts=current_facts)!=before
    physical,installation,epoch,environment=facts
    foreign=([str(physical[0])+'0',physical[1]],installation,epoch,environment)
    assert receipts._subject_for_revision(c,c.info.dsn,'PAPER',row,facts=foreign)!=before
    c.rollback()


@pytest.mark.parametrize('scope,paper',[('DASHBOARD',True),('unknown',True),('PAPER',False)])
def test_owned_invalid_selection_refuses_before_database_access(scope,paper):
    class NoQueries:
        def execute(self,*_args,**_kwargs):pytest.fail('invalid selection queried the borrowed connection')
    with pytest.raises(ValueError,match='scope'):
        receipts.read_owned(NoQueries(),'unused',only_scope=scope,include_paper=paper)


def test_a_removed_owned_snapshot_boundary_is_detected(operational,monkeypatch):
    original=receipts.read_owned
    def detached(_caller,database_url,**options):
        with psycopg.connect(database_url) as later:
            later.execute('BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            return original(later,database_url,**options)
    monkeypatch.setattr(receipts,'read_owned',detached)
    try:
        with pytest.raises(AssertionError):
            test_owned_receipt_read_keeps_snapshot_across_a_concurrent_negative_commit(operational)
    finally:
        operational[0].rollback()
