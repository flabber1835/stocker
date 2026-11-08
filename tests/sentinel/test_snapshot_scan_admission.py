"""Native PostgreSQL admission, fresh MVCC snapshots and borrowed-work safety."""
from threading import Event,Thread
from contextlib import nullcontext
import time

import psycopg
import pytest

from sentinel import committed_read, snapshot_scan_admission as gate
from tests.sentinel.test_rolling_snapshot_publisher import pg  # noqa: F401


def test_native_admission_serializes_and_acquires_snapshot_after_wait(pg):
    first=psycopg.connect(pg.sync_dsn);second=psycopg.connect(pg.sync_dsn)
    acquired=Event();finished=[]
    with first.transaction():first.execute('CREATE TABLE gate_probe(value integer)')
    def waiting():
        with committed_read.proof_connection(second,serialize_snapshot=True) as proof:
            acquired.set();finished.append(proof.execute('SELECT value FROM gate_probe').fetchall())
    try:
        with gate.admitted(first):
            thread=Thread(target=waiting);thread.start()
            time.sleep(.05);assert not acquired.is_set()
            first.execute('INSERT INTO gate_probe VALUES(7)');first.commit()
        thread.join(timeout=2)
        assert not thread.is_alive() and acquired.is_set() and finished==[[(7,)]]
    finally:
        if 'thread' in locals():thread.join(timeout=2)
        first.rollback();first.execute('DROP TABLE IF EXISTS gate_probe');first.commit()
        first.close();second.close()


def test_native_admission_timeout_and_exception_release_without_timeout_drift(pg):
    first=psycopg.connect(pg.sync_dsn);second=psycopg.connect(pg.sync_dsn)
    try:
        second.execute("SET statement_timeout='37ms'");second.commit()
        with gate.admitted(first):
            with pytest.raises((psycopg.errors.QueryCanceled,psycopg.errors.LockNotAvailable)):
                with gate.admitted(second,wait_seconds=.03):pytest.fail('contended admission was granted')
        assert second.execute('SHOW statement_timeout').fetchone()==('37ms',);second.rollback()
        with pytest.raises(ValueError,match='proof failed'):
            with gate.admitted(first):raise ValueError('proof failed')
        with gate.admitted(second,wait_seconds=.03):pass
    finally:first.close();second.close()


def test_borrowed_transaction_is_not_committed_or_rolled_back(pg):
    connection=psycopg.connect(pg.sync_dsn)
    try:
        connection.execute('CREATE TEMP TABLE untouched(value integer)')
        connection.execute('INSERT INTO untouched VALUES(5)')
        with committed_read.proof_connection(connection,serialize_snapshot=True) as proof:
            assert proof is not connection
            assert proof.execute('SHOW transaction_read_only').fetchone()==('on',)
        assert connection.execute('SELECT * FROM untouched').fetchall()==[(5,)]
    finally:connection.rollback();connection.close()


def test_removed_native_admission_is_detected(pg,monkeypatch):
    original=gate.admitted
    # Retain the competing owner lock, remove only proof-connection admission.
    monkeypatch.setattr(committed_read,'nullcontext',nullcontext)
    def missing(connection,**kwargs):
        return original(connection,**kwargs) if connection is owner[0] else nullcontext()
    owner=[]
    real_connect=psycopg.connect
    def connect(*a,**kw):
        connection=real_connect(*a,**kw)
        if not owner:owner.append(connection)
        return connection
    monkeypatch.setattr(psycopg,'connect',connect)
    monkeypatch.setattr(gate,'admitted',missing)
    with pytest.raises(AssertionError):
        test_native_admission_serializes_and_acquires_snapshot_after_wait(pg)
