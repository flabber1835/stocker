"""A display observer cannot stall a financial revision writer."""
import inspect,textwrap
import psycopg
import pytest
from sentinel.panel import projection_service as producer,verification_service as verifier,model,sources
from tests.sentinel.test_operational_projection_service import operational,conn,pg


def test_financial_revision_update_can_commit_during_display_fence(operational):
    c,_,_=operational
    c.execute("INSERT INTO sentinel_processed_sessions(cursor_name,session,state) VALUES ('opening-isolation-test','2031-04-21','{}')")
    c.commit()
    producer.lock_inputs(c)
    with psycopg.connect(c.info.dsn) as writer:
        writer.execute("SET LOCAL lock_timeout='100ms'")
        writer.execute("UPDATE sentinel_processed_sessions SET state='{\"updated\":true}' WHERE cursor_name='opening-isolation-test'")
        writer.commit()
    c.rollback()


def test_removed_compatible_lock_fails_concurrent_writer(operational,monkeypatch):
    code=textwrap.dedent(inspect.getsource(producer.lock_inputs))
    assert 'FOR KEY SHARE' in code
    namespace=dict(vars(producer));exec(code.replace('FOR KEY SHARE','FOR SHARE'),namespace)
    monkeypatch.setattr(producer,'lock_inputs',namespace['lock_inputs'])
    with pytest.raises(psycopg.errors.LockNotAvailable):
        test_financial_revision_update_can_commit_during_display_fence(operational)


def test_paper_observation_uses_one_snapshot_across_a_concurrent_commit(operational,monkeypatch):
    c,_,_=operational
    c.execute('CREATE TABLE opening_read_fixture(value integer)');c.execute('INSERT INTO opening_read_fixture VALUES(1)');c.commit()
    monkeypatch.setattr(verifier.read_projection,'subject_for',lambda *a:'same')
    def observe(reader,**kwargs):
        before=reader.execute('SELECT value FROM opening_read_fixture').fetchone()[0]
        with psycopg.connect(c.info.dsn) as writer:
            writer.execute('UPDATE opening_read_fixture SET value=2');writer.commit()
        assert reader.execute('SHOW transaction_read_only').fetchone()==('on',)
        assert reader.execute('SELECT value FROM opening_read_fixture').fetchone()==(before,)
        return model.Row('paper_reconciliation','PAPER','PENDING',model.WARN)
    monkeypatch.setattr(sources,'_dual_paper_row',observe)
    verifier._observe_once(c.info.dsn,True,'same')


def test_removed_repeatable_snapshot_fails_observation(operational,monkeypatch):
    code=textwrap.dedent(inspect.getsource(verifier._observe_once))
    namespace=dict(vars(verifier));exec(code.replace('ISOLATION LEVEL REPEATABLE READ READ ONLY','READ ONLY'),namespace)
    monkeypatch.setattr(verifier,'_observe_once',namespace['_observe_once'])
    with pytest.raises(AssertionError):
        test_paper_observation_uses_one_snapshot_across_a_concurrent_commit(operational,monkeypatch)
