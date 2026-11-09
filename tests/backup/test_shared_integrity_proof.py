"""Fresh-process production admission against the strict private-media adapter."""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import base64
import json
import inspect
import multiprocessing
import re
from types import SimpleNamespace
from textwrap import dedent

import pytest
from psycopg.pq import TransactionStatus

from sentinel import backup_integrity_reuse as reuse, backup_runtime_authority as authority
from lab import NOW, Cursor, Database, Media, wal_name


class NativeMetadataCursor(Cursor):
    def execute(self, sql, params=()):
        super().execute(sql, params)
        if sql.startswith('SELECT name,(pg_stat_file'):
            # The older adapter preserves filesystem nanoseconds. Real
            # pg_stat_file returns timestamptz, which the receipt must encode.
            epoch=datetime(1970,1,1,tzinfo=timezone.utc)
            self.rows=[tuple(epoch+timedelta(microseconds=v//1000)
                if i in {2,3,5,6} and v is not None else v
                for i,v in enumerate(row)) for row in self.rows]


class SharedDatabase(Database):
    def __init__(self, media):
        super().__init__(media)
        self.info=SimpleNamespace(transaction_status=TransactionStatus.INTRANS)
        self.uptime=1000.0;self.boot='12345678-1234-1234-1234-123456789abc'
        self.postmaster=NOW;self.busy=False;self.publications=0
        self.receipt=media.root/reuse.NAME

    @contextmanager
    def transaction(self): yield

    def cursor(self):return NativeMetadataCursor(self)

    def execute(self, sql, params=()):
        if sql.startswith('SELECT pg_postmaster_start_time()'):
            row=(self.postmaster,'private-test',self.boot,f'{self.uptime} 0.0')
        elif sql=='SELECT pg_read_binary_file(%s,0,%s,true)' and params[0]==reuse.NAME:
            row=(self.receipt.read_bytes() if self.receipt.exists() else None,)
        elif sql=='SELECT pg_try_advisory_lock(%s)' and self.busy:
            row=(False,)
        elif sql.startswith('COPY (SELECT '):
            encoded=re.match(r"COPY \(SELECT '([A-Za-z0-9+/=]+)'\)",sql)[1]
            self.receipt.write_bytes(base64.b64decode(encoded));self.publications+=1;row=(None,)
        else:
            cursor=self.cursor();cursor.execute(sql,params);return cursor
        return SimpleNamespace(fetchone=lambda:row)


@pytest.fixture
def world(tmp_path, monkeypatch):
    value=SharedDatabase(Media(tmp_path/'media'))
    monkeypatch.setenv(authority.AUTHORITY_ENV,authority.AUTHORITY_VALUE)
    monkeypatch.setenv('SENTINEL_PUBLICATION_RECEIPT_KEY','synthetic-shared-integrity-proof-key')
    monkeypatch.setattr(reuse,'selected',lambda:True)
    monkeypatch.setattr(authority.time,'monotonic',lambda:value.uptime)
    return value


def admit(world): return authority.require(world,operation='private shared-proof admission')


def test_fresh_process_reuses_authenticated_proof_without_payload_reads(world):
    assert admit(world)['integrity_objects_hashed']==8
    receiver,sender=multiprocessing.get_context('fork').Pipe(duplex=False)
    def child():
        authority._PROOF_CACHE.clear()
        sender.send(admit(world));sender.close()
    process=multiprocessing.get_context('fork').Process(target=child)
    process.start();sender.close();process.join(5)
    assert not process.is_alive() and process.exitcode==0
    result=receiver.recv();receiver.close();process.close()
    assert result['integrity_objects_hashed']==0 and not result['integrity_full_scrub']
    assert world.commits==0 and world.locks=={}


def test_metadata_hits_do_not_rewrite_receipt_or_renew_expiry(world):
    admit(world);raw=world.receipt.read_bytes();world.uptime+=250
    assert admit(world)['integrity_objects_hashed']==0
    assert world.receipt.read_bytes()==raw and world.publications==1
    world.uptime+=50
    assert admit(world)['integrity_objects_hashed']==8


def test_new_tail_hashes_only_new_bytes_and_preserves_original_scrub_clock(world):
    admit(world);stamp=json.loads(world.receipt.read_bytes())['proof']['completed_uptime']
    world.uptime+=200;world.media.segment(6);world.frontier=wal_name(6)
    assert admit(world)['integrity_objects_hashed']==2
    assert json.loads(world.receipt.read_bytes())['proof']['completed_uptime']==stamp
    world.uptime+=100
    assert admit(world)['integrity_objects_hashed']==10


@pytest.mark.parametrize('changed',['postmaster','boot','implementation','rollback','expiry'])
def test_foreign_or_expired_receipt_never_grants_reuse(world,monkeypatch,changed):
    admit(world)
    if changed=='postmaster':world.postmaster+=timedelta(seconds=1)
    elif changed=='boot':world.boot='87654321-1234-1234-1234-123456789abc'
    elif changed=='implementation':monkeypatch.setattr(reuse,'implementation',lambda:'different-implementation')
    elif changed=='rollback':world.uptime-=1
    else:world.uptime+=300
    assert admit(world)['integrity_objects_hashed']==8


def test_forged_receipt_refuses_and_never_takes_account_ownership(world):
    admit(world);envelope=json.loads(world.receipt.read_bytes())
    envelope['proof']['completed_uptime']+=100
    world.receipt.write_text(json.dumps(envelope))
    with pytest.raises(authority.BackupRuntimeRefused,match='reuse record'):
        admit(world)
    assert world.locks=={} and world.commits==0


def test_concurrent_cold_owner_refuses_before_reading_archive_payload(world,monkeypatch):
    world.busy=True;calls=[]
    monkeypatch.setattr(authority,'_hash_objects',lambda *a,**k:calls.append(True))
    with pytest.raises(authority.BackupRuntimeUnavailable,match='another backup integrity'):
        admit(world)
    assert calls==[] and not world.receipt.exists()


def test_receipt_does_not_hide_missing_archive_or_changed_bytes(world):
    admit(world)
    with (world.media.namespace/wal_name(4)).open('r+b') as stream:
        stream.write(b'corruption')
    with pytest.raises(authority.BackupRuntimeRefused,match='SHA-256'):
        admit(world)


def test_same_metadata_corruption_is_found_at_original_expiry(world,monkeypatch):
    admit(world)
    original=authority._archive_metadata
    stable=original(world,root=f'{authority.WAL_ROOT}/cluster-{world.system_id}',
                    objects=tuple(wal_name(i) for i in range(2,6)))
    monkeypatch.setattr(authority,'_archive_metadata',lambda *a,**k:stable)
    with (world.media.namespace/wal_name(4)).open('r+b') as stream:stream.write(b'corruption')
    world.uptime+=299
    assert admit(world)['integrity_objects_hashed']==0
    world.uptime+=1
    with pytest.raises(authority.BackupRuntimeRefused,match='SHA-256'):
        admit(world)


def test_live_never_selects_paper_shared_proof(monkeypatch):
    monkeypatch.setenv('ALPACA_BASE_URL','https://api.alpaca.markets')
    # Call the original implementation, not the private-media fixture override.
    assert not reuse.selected()


def test_a_failed_full_proof_invalidates_the_shared_positive(world,monkeypatch):
    admit(world)
    original=authority._hash_objects
    monkeypatch.setattr(authority,'_hash_objects',lambda *a,**k:(_ for _ in ()).throw(
        authority.BackupRuntimeUnavailable('synthetic archive read failed')))
    world.uptime+=300
    with pytest.raises(authority.BackupRuntimeUnavailable,match='synthetic'):
        admit(world)
    assert json.loads(world.receipt.read_bytes())['proof']['outcome']=='INVALID'
    monkeypatch.setattr(authority,'_hash_objects',original)
    assert admit(world)['integrity_full_scrub']


def test_removed_receipt_authentication_has_executed_falsifier(world,monkeypatch):
    text=dedent(inspect.getsource(reuse.Owner.__init__))
    guard="not hmac.compare_digest(envelope['signature'], _signature(envelope['proof']))"
    assert text.count(guard)==1
    namespace=dict(vars(reuse));exec(compile(text.replace(guard,'False'),'<removed integrity authentication>','exec'),namespace)
    monkeypatch.setattr(reuse.Owner,'__init__',namespace['__init__'])
    with pytest.raises((AssertionError,pytest.fail.Exception)):
        test_forged_receipt_refuses_and_never_takes_account_ownership(world)
