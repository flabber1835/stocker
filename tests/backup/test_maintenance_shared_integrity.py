"""Native common-owner protocol; synthetic media is not restore qualification.

The disposable PostgreSQL server actually uses 1 MiB WAL segments. No positive
test substitutes policy selection, filesystem metadata, SQL hashes or locks.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import inspect
import itertools
import json
import os
from pathlib import Path
import select
import shutil
import subprocess
import sys
import time
from unittest.mock import patch

import psycopg
import pytest

from sentinel import backup_integrity_reuse as reuse
from sentinel import backup_maintenance_integrity as maintenance
from sentinel import backup_runtime_authority as authority
from tests.support import postgres


ACCOUNT = 'PAprivateCommonProof'
SIZE = 1024**2
_counter = itertools.count(1)


def _selected(monkeypatch):
    for name, value in {
        'ALPACA_BASE_URL': 'https://paper-api.alpaca.markets',
        'SENTINEL_LOCAL_PAPER_MODE': 'OWNER_AUTHORIZED_FUNCTION_FIRST_V1',
        'SENTINEL_LOCAL_PAPER_ACCOUNT_ID': ACCOUNT,
        'SENTINEL_LOCAL_PAPER_BACKUP_POLICY': 'REQUIRED_V1',
        'SENTINEL_RUNTIME_BACKUP_AUTHORITY': 'REQUIRED_V1',
        'SENTINEL_PUBLICATION_RECEIPT_KEY': 'private-test-receipt-key-no-authority-0123456789',
    }.items():
        monkeypatch.setenv(name, value)
    assert reuse.selected() and authority.enabled()


def _wait_archive(conn, old=None):
    deadline = time.monotonic()+12
    while time.monotonic() < deadline:
        conn.execute('SELECT pg_stat_clear_snapshot()')
        name = conn.execute('SELECT last_archived_wal FROM pg_stat_archiver').fetchone()[0]
        if name and (old is None or name > old):
            return name
        time.sleep(.05)
    pytest.fail('private PostgreSQL did not archive its switched segment')


@pytest.fixture(scope='module')
def native_cluster():
    server = postgres._EphemeralPostgres()
    run = postgres._run

    def small_wal(cmd, **kwargs):
        # Configure a real supported server geometry, rather than substitute the
        # runtime current_setting() query or pretend truncated files are WAL.
        if any(Path(word).name == 'initdb' for word in cmd):
            cmd = [*cmd, '--wal-segsize=1']
        return run(cmd, **kwargs)

    try:
        with patch.object(postgres, '_run', small_wal):
            server.start()
        with psycopg.connect(server.sync_dsn, autocommit=True) as conn:
            conn.execute('CREATE TABLE sentinel_account_binding ('
                'id integer PRIMARY KEY,deployment_id text,broker text,broker_account_id text,'
                'takeover_epoch integer,ownership_state text,notes text)')
            conn.execute("INSERT INTO sentinel_account_binding VALUES "
                "(1,'private-native','alpaca',%s,1,'SENTINEL_OWNED','synthetic fixture')", (ACCOUNT,))
        server.enable_archive()
        with psycopg.connect(server.sync_dsn, autocommit=True) as conn:
            assert conn.execute("SELECT pg_size_bytes(current_setting('wal_segment_size'))").fetchone()[0] == SIZE
            for number in range(2):
                old = _wait_archive(conn)
                conn.execute('SELECT pg_create_restore_point(%s)', (f'private-common-{number}',))
                conn.execute('SELECT pg_switch_wal()')
                _wait_archive(conn, old)
        yield server
    finally:
        server.stop()


class Media:
    def __init__(self, server, conn):
        self.server, self.conn = server, conn
        self.system = authority.current_system_id(conn)
        self.base = f'base-20261109T{next(_counter):06d}Z'
        self.root = Path(server.datadir)/self.base
        self.base_root, self.wal_root = self.root/'base', self.root/'wal'
        self.namespace = self.wal_root/f'cluster-{self.system}'
        self.directory = self.base_root/self.base
        self.directory.mkdir(parents=True)
        self.namespace.mkdir(parents=True)
        self.end = _wait_archive(conn)
        end_index = int(self.end[8:16], 16)*(2**32//SIZE)+int(self.end[16:], 16)
        self.names = tuple(self.name(i) for i in (end_index-1, end_index))
        self.start = self.names[0]
        self.copy_archive(self.names)
        for root in (self.base_root, self.wal_root):
            (root/authority.MARKER).write_text(authority.MARKER_CONTENT+'\n')
        lsn = (end_index-1)*SIZE+64
        (self.directory/'backup_manifest').write_text(json.dumps({'WAL-Ranges': [
            {'Timeline': 1, 'End-LSN': f'{lsn >> 32:X}/{lsn & 0xffffffff:X}'}]}))
        (self.directory/'backup_label').write_text('synthetic metadata, not a backup qualification\n')
        (self.directory/'sentinel-pitr-base-identity').write_text(f'system_identifier={self.system}\n')
        (self.directory/'sentinel-recovery-marker').write_text(
            f'marker=sentinel-backup-20261109T000000Z-1\nlsn=0/1\nwal={self.end}\nsystem_identifier={self.system}\n')
        self.select(self.base)
        self.chown()

    @staticmethod
    def name(index):
        log, segment = divmod(index, 2**32//SIZE)
        return f'00000001{log:08X}{segment:08X}'

    def chown(self):
        if os.geteuid() == 0:
            for path in (self.root, *self.root.rglob('*')):
                shutil.chown(path, user='postgres', group='postgres')

    def select(self, base):
        selection = self.base_root/f'.sentinel-runtime-base-{self.system}-v1'
        selection.write_text(
            f'schema=sentinel.runtime-base/1\nsystem_identifier={self.system}\nbase_backup={base}\n')
        if os.geteuid() == 0:
            shutil.chown(selection, user='postgres', group='postgres')

    def copy_archive(self, names):
        for name in names:
            path = self.namespace/name
            shutil.copyfile(Path(self.server.datadir)/'worker-archive'/name, path)
            path.with_name(name+'.sha256').write_text('sha256='+hashlib.sha256(path.read_bytes()).hexdigest()+'\n')
            if os.geteuid() == 0:
                for created in (path, path.with_name(name+'.sha256')):
                    shutil.chown(created, user='postgres', group='postgres')

    def advance(self):
        old = self.end
        self.conn.execute('SELECT pg_create_restore_point(%s)', (f'private-advance-{self.base}',))
        self.conn.execute('SELECT pg_switch_wal()')
        self.end = _wait_archive(self.conn, old)
        names = authority._expected_wals(old, self.end, segment_size=SIZE)[1:]
        self.copy_archive(names)
        self.names += names

    def receipt(self):
        return json.loads((Path(self.server.datadir)/reuse.NAME).read_bytes())

    def rewrite_receipt(self, change):
        value = self.receipt()
        change(value['proof'])
        value['signature'] = reuse._signature(value['proof'])
        self.conn.execute(reuse._publish_sql(reuse._canonical(value)))

    def prove(self, kind='maintenance', **overrides):
        if kind == 'application':
            return authority.require(self.conn, operation='private application', allow_continuity=False)
        args = dict(base_backup=self.base, system_identifier=self.system,
                    wal_segment_bytes=SIZE, observed_frontier=self.end, wait_seconds=0)
        return maintenance.prove(self.conn, **(args | overrides)).model_dump()

    def child_arguments(self, kind):
        return dict(dsn=self.server.sync_dsn, base_root=str(self.base_root), wal_root=str(self.wal_root),
                    base_backup=self.base, system_identifier=self.system,
                    wal_segment_bytes=SIZE, observed_frontier=self.end, kind=kind)

    def child(self, kind):
        result = subprocess.run([sys.executable, '-c', CHILD, json.dumps(self.child_arguments(kind))],
            capture_output=True, text=True, timeout=20, env=dict(os.environ))
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)


CHILD = '''
import json,sys,psycopg
from sentinel import backup_runtime_authority as a, backup_integrity_reuse as r
from sentinel import backup_maintenance_integrity as m
v=json.loads(sys.argv[1]); a.BASE_ROOT=v.pop('base_root');a.WAL_ROOT=v.pop('wal_root')
dsn=v.pop('dsn');kind=v.pop('kind');reads=[];original=a._hash_objects
def count(*args,**kwargs):
    reads.extend(kwargs['objects']);return original(*args,**kwargs)
a._hash_objects=count
assert r.selected() and a.enabled()
with psycopg.connect(dsn,autocommit=True) as c:
    try:
        result=(m.prove(c,**v,wait_seconds=0).model_dump() if kind=='maintenance'
                else a.require(c,operation='private child',allow_continuity=False))
        print(json.dumps({'ok':True,'result':result,'reads':len(reads)}))
    except (a.BackupRuntimeRefused,a.BackupRuntimeUnavailable) as e:
        print(json.dumps({'ok':False,'error':type(e).__name__,'reads':len(reads)}))
'''


@pytest.fixture
def media(native_cluster, monkeypatch):
    _selected(monkeypatch)
    # Tests share only the disposable server, never trusted evidence or the
    # deliberately malformed receipt left by another negative case.
    (Path(native_cluster.datadir)/reuse.NAME).unlink(missing_ok=True)
    with psycopg.connect(native_cluster.sync_dsn, autocommit=True) as conn:
        fixture = Media(native_cluster, conn)
        monkeypatch.setattr(authority, 'BASE_ROOT', str(fixture.base_root))
        monkeypatch.setattr(authority, 'WAL_ROOT', str(fixture.wal_root))
        yield fixture


@contextmanager
def count_reads(monkeypatch):
    reads = []
    original = authority._hash_objects
    def counted(*args, **kwargs):
        reads.extend(kwargs['objects'])
        return original(*args, **kwargs)
    with monkeypatch.context() as local:
        local.setattr(authority, '_hash_objects', counted)
        yield reads


@pytest.mark.parametrize('first,second', [('maintenance', 'application'), ('application', 'maintenance')])
def test_fresh_processes_share_actual_two_pass_proof_in_both_directions(media, first, second):
    initial = media.child(first)
    assert initial['ok'] and initial['reads'] == 4
    assert initial['result']['integrity_full_scrub'] is True
    stamp = media.receipt()['proof']['completed_uptime']
    hit = media.child(second)
    assert hit['ok'] and hit['reads'] == 0
    assert hit['result']['integrity_full_scrub'] is False
    assert hit['result']['integrity_objects_hashed'] == 0
    assert media.receipt()['proof']['completed_uptime'] == stamp
    if second == 'maintenance':
        assert hit['result']['integrity_completed_uptime'] == stamp


def test_incremental_bytes_do_not_renew_original_full_clock(media, monkeypatch):
    media.prove()
    stamp = media.receipt()['proof']['completed_uptime']
    media.advance()
    with count_reads(monkeypatch) as reads:
        incremental = media.prove()
    assert len(reads) == 2 and incremental['integrity_objects_hashed'] == 2
    assert incremental['integrity_full_scrub'] is False
    assert incremental['integrity_completed_uptime'] == stamp
    with count_reads(monkeypatch) as reads:
        assert media.prove('application')['integrity_objects_hashed'] == 0
    assert reads == [] and media.receipt()['proof']['completed_uptime'] == stamp


def test_competing_process_cannot_scrub_and_reentrant_counts_balance(media):
    with psycopg.connect(media.server.sync_dsn, autocommit=True) as owner:
        owner.execute('SELECT pg_advisory_lock(%s)', (reuse.LOCK_KEY,))
        for kind in ('maintenance', 'application'):
            result = media.child(kind)
            assert result == {'ok': False, 'error': 'BackupIntegrityBusy', 'reads': 0}
        assert owner.execute('SELECT pg_advisory_unlock(%s)', (reuse.LOCK_KEY,)).fetchone() == (True,)
    media.prove()
    with psycopg.connect(media.server.sync_dsn, autocommit=True) as other:
        assert other.execute('SELECT pg_try_advisory_lock(%s)', (reuse.LOCK_KEY,)).fetchone() == (True,)
        assert other.execute('SELECT pg_advisory_unlock(%s)', (reuse.LOCK_KEY,)).fetchone() == (True,)
    assert media.conn.execute('SELECT pg_advisory_unlock(%s)', (reuse.LOCK_KEY,)).fetchone() == (False,)


def test_terminated_private_worker_releases_both_lock_counts(media):
    media.prove()
    boundary = "reads.extend(kwargs['objects']);return original(*args,**kwargs)"
    assert CHILD.count(boundary) == 1
    blocked = CHILD.replace(boundary,
        "print('OWNED',flush=True);__import__('time').sleep(30);return original(*args,**kwargs)")
    worker = subprocess.Popen([sys.executable, '-c', blocked,
        json.dumps(media.child_arguments('maintenance'))], stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True, env=dict(os.environ))
    try:
        assert select.select([worker.stdout], [], [], 10)[0], 'private worker never acquired proof ownership'
        assert worker.stdout.readline().strip() == 'OWNED'
        assert media.conn.execute('SELECT pg_try_advisory_lock(%s)', (reuse.LOCK_KEY,)).fetchone() == (False,)
        worker.terminate()
        worker.wait(timeout=5)
        deadline = time.monotonic()+5
        while time.monotonic() < deadline:
            if media.conn.execute('SELECT pg_try_advisory_lock(%s)', (reuse.LOCK_KEY,)).fetchone() == (True,):
                assert media.conn.execute('SELECT pg_advisory_unlock(%s)', (reuse.LOCK_KEY,)).fetchone() == (True,)
                break
            time.sleep(.05)
        else:
            pytest.fail('dead worker retained common proof ownership')
        assert media.child('application')['ok'] is True
    finally:
        if worker.poll() is None:
            worker.kill()
        worker.communicate(timeout=5)


def test_bridge_refuses_borrowed_transaction_without_committing_it(media):
    with psycopg.connect(media.server.sync_dsn) as borrowed:
        borrowed.execute('CREATE TEMP TABLE caller_work(value integer)')
        borrowed.commit()
        borrowed.execute('INSERT INTO caller_work VALUES (1)')
        with pytest.raises(authority.BackupRuntimeRefused, match='owned session'):
            maintenance.prove(borrowed, base_backup=media.base, system_identifier=media.system,
                wal_segment_bytes=SIZE, observed_frontier=media.end, wait_seconds=0)
        borrowed.rollback()
        assert borrowed.execute('SELECT count(*) FROM caller_work').fetchone() == (0,)


def expire_proof_clock(monkeypatch):
    """Advance past the 300-second window without forging a pre-boot completion."""
    original = reuse._clock

    def advanced(conn):
        physical, boot, uptime, before = original(conn)
        return physical, boot, uptime + 301, before

    monkeypatch.setattr(reuse, '_clock', advanced)


@pytest.mark.parametrize('change', [
    pytest.param(None, id='expired'),
    lambda p: p.update(completed_uptime=p['completed_uptime']+301),
    lambda p: p.update(boot='00000000-0000-0000-0000-000000000000'),
    lambda p: p['context'].update(postmaster='2000-01-01T00:00:00+00:00'),
    lambda p: p['context'].update(implementation='0'*64),
    lambda p: p['context'].update(segment_size=SIZE*2),
    lambda p: p['context'].update(system_id='1'),
])
def test_expired_or_foreign_receipt_requires_real_full_scrub(media, monkeypatch, change):
    media.prove()
    if change is None:
        expire_proof_clock(monkeypatch)
    else:
        media.rewrite_receipt(change)
    with count_reads(monkeypatch) as reads:
        result = media.prove()
    assert result['integrity_full_scrub'] is True and len(reads) == 4


@pytest.mark.parametrize('damage', ['missing', 'truncated', 'checksum-missing', 'checksum-wrong',
    'symlink', 'hardlink', 'sidecar-symlink'])
def test_new_negative_media_refuses_hit_and_invalidates_shared_positive(media, damage):
    media.prove()
    payload = media.namespace/media.start
    sidecar = payload.with_name(payload.name+'.sha256')
    if damage == 'missing':
        payload.unlink()
    elif damage == 'truncated':
        with payload.open('r+b') as stream:
            stream.truncate(SIZE-1)
    elif damage == 'checksum-missing':
        sidecar.unlink()
    elif damage == 'checksum-wrong':
        sidecar.write_text('sha256='+'0'*64+'\n')
    else:
        target = sidecar if damage == 'sidecar-symlink' else payload
        retained = target.with_name(target.name+'.retained')
        target.rename(retained)
        if damage == 'hardlink':
            os.link(retained, target)
        else:
            target.symlink_to(retained)
    with pytest.raises((authority.BackupRuntimeRefused, authority.BackupRuntimeUnavailable)):
        media.prove()
    assert media.receipt()['proof']['outcome'] == 'INVALID'
    assert media.conn.execute('SELECT pg_advisory_unlock(%s)', (reuse.LOCK_KEY,)).fetchone() == (False,)


@pytest.mark.parametrize('root', ['base_root', 'wal_root'])
def test_missing_durable_marker_is_checked_even_for_a_shared_hit(media, root):
    media.prove()
    (getattr(media, root)/authority.MARKER).unlink()
    with pytest.raises(authority.BackupRuntimeUnavailable):
        media.prove()


def test_current_base_selection_is_not_a_pinned_maintenance_base(media):
    media.prove()
    successor = 'base-20261110T235959Z'
    shutil.copytree(media.directory, media.base_root/successor)
    media.select(successor)
    with pytest.raises(authority.BackupIntegritySelectionMoved):
        media.prove()
    assert media.prove('application')['base_backup'] == successor


def test_second_authenticated_owner_observation_exports_only_expired_clocks(media, monkeypatch):
    original = authority.require
    def expire_after_full_proof(*args, **kwargs):
        result = original(*args, **kwargs)
        expire_proof_clock(monkeypatch)
        return result
    monkeypatch.setattr(authority, 'require', expire_after_full_proof)
    trace = maintenance._Trace()
    with pytest.raises(authority.BackupIntegrityProofExpired) as caught:
        maintenance.prove(media.conn, base_backup=media.base, system_identifier=media.system,
            wal_segment_bytes=SIZE, observed_frontier=media.end, wait_seconds=0, _trace=trace)
    owner = reuse.Owner(media.conn, dict(system_id=media.system, base=media.base,
        start=media.start, segment_size=SIZE))
    assert owner.proof is None and owner.cached() is None
    assert type(owner.expired_window) is tuple and len(owner.expired_window) == 2
    assert owner.expired_window[1]-owner.expired_window[0] >= 300
    failure = maintenance.failure_record(caught.value, trace)
    assert failure.code == 'PROOF_WINDOW_EXPIRED' and failure.retryable
    assert failure.stage == 'RESULT' and failure.cleanup.proof_lock == 'RELEASED'


def test_new_base_is_retryable_only_after_same_physical_proof_and_reobservation(media):
    successor = 'base-20261110T235956Z'
    shutil.copytree(media.directory, media.base_root/successor)
    media.select(successor)
    trace = maintenance._Trace()
    with pytest.raises(authority.BackupIntegritySelectionMoved) as caught:
        maintenance.prove(media.conn, base_backup=media.base, system_identifier=media.system,
            wal_segment_bytes=SIZE, observed_frontier=media.end, wait_seconds=0, _trace=trace)
    failure = maintenance.failure_record(caught.value, trace)
    assert failure.code == 'SELECTION_MOVED' and failure.retryable
    assert media.prove(base_backup=successor)['base_backup'] == successor
    with pytest.raises(authority.BackupRuntimeRefused):
        media.prove(base_backup=media.base, wal_segment_bytes=SIZE*2)


@pytest.mark.parametrize('bad', [None, '../foreign', 42])
def test_malformed_returned_base_cannot_be_classified_as_selection_movement(media, monkeypatch, bad):
    original = authority.require
    def malformed(*args, **kwargs):
        return dict(original(*args, **kwargs), base_backup=bad)
    monkeypatch.setattr(authority, 'require', malformed)
    trace = maintenance._Trace()
    with pytest.raises(authority.BackupRuntimeRefused) as caught:
        maintenance.prove(media.conn, base_backup=media.base, system_identifier=media.system,
            wal_segment_bytes=SIZE, observed_frontier=media.end, wait_seconds=0, _trace=trace)
    failure = maintenance.failure_record(caught.value, trace)
    assert failure.code == 'INTEGRITY_REFUSED' and failure.retryable is False


def test_removed_returned_base_shape_guard_has_an_executed_falsifier(media, monkeypatch):
    source = inspect.getsource(maintenance.prove)
    guard = ("if (type(current_base) is not str\n"
             "                    or re.fullmatch(r'base-[0-9]{8}T[0-9]{6}Z', current_base) is None):")
    assert source.count(guard) == 1
    namespace = vars(maintenance).copy()
    exec(compile(source.replace(guard, 'if False:'), '<removed base identity shape>', 'exec'), namespace)
    monkeypatch.setattr(maintenance, 'prove', namespace['prove'])
    with pytest.raises(authority.BackupIntegritySelectionMoved):
        test_malformed_returned_base_cannot_be_classified_as_selection_movement(media, monkeypatch, None)


def test_selection_movement_during_proof_refuses_and_invalidates(media, monkeypatch):
    media.prove()
    original = authority._hash_objects
    moved = False
    def changing(*args, **kwargs):
        nonlocal moved
        result = original(*args, **kwargs)
        if not moved:
            moved = True
            media.select('base-20261110T235958Z')
        return result
    monkeypatch.setattr(authority, '_hash_objects', changing)
    with pytest.raises(authority.BackupRuntimeUnavailable, match='selection changed'):
        media.prove()
    assert media.receipt()['proof']['outcome'] == 'INVALID'


@pytest.mark.parametrize('bad', ['signature', 'malformed'])
def test_untrusted_receipt_never_grants_reuse(media, bad):
    media.prove()
    raw = media.receipt()
    if bad == 'signature':
        raw['signature'] = '0'*64
        payload = reuse._canonical(raw)
    else:
        payload = b'{malformed'
    media.conn.execute(reuse._publish_sql(payload))
    with pytest.raises(authority.BackupRuntimeRefused, match='record or clock'):
        media.prove()


def test_same_metadata_corruption_is_caught_by_original_expiry(media, monkeypatch):
    payload = media.namespace/media.start
    original_byte = payload.read_bytes()[:1]
    # pg_stat_file exposes second-resolution modification/change clocks. Bound
    # this genuine same-second filesystem experiment; do not fake its metadata.
    for attempt in range(4):
        with payload.open('r+b') as stream:
            stream.write(original_byte)
        delay = 1.02-(time.time() % 1)
        time.sleep(delay)
        os.utime(payload, None)
        before = authority._archive_metadata(media.conn, root=str(media.namespace), objects=media.names)
        media.prove()
        stamp = payload.stat().st_mtime_ns
        with payload.open('r+b') as stream:
            stream.write(bytes([original_byte[0] ^ 0xff]))
        os.utime(payload, ns=(payload.stat().st_atime_ns, stamp))
        after = authority._archive_metadata(media.conn, root=str(media.namespace), objects=media.names)
        if before == after:
            break
    else:
        pytest.fail('could not construct bounded real same-second metadata case')
    with count_reads(monkeypatch) as reads:
        assert media.prove()['integrity_objects_hashed'] == 0
    assert reads == []
    expire_proof_clock(monkeypatch)
    with pytest.raises(authority.BackupRuntimeRefused, match='SHA-256'):
        media.prove()
    assert media.receipt()['proof']['outcome'] == 'INVALID'


@pytest.mark.parametrize('override', [
    {'system_identifier': '1'}, {'wal_segment_bytes': SIZE*2},
    {'observed_frontier': '000000020000000000000002'},
    {'observed_frontier': '000000010000FFFF00000001'},
])
def test_host_observation_must_match_actual_selected_media(media, override):
    with pytest.raises(authority.BackupRuntimeRefused):
        media.prove(**override)


def test_unselected_policy_cannot_use_maintenance_bridge(media, monkeypatch):
    media.prove()
    monkeypatch.setenv('SENTINEL_LOCAL_PAPER_BACKUP_POLICY', '')
    with pytest.raises(authority.BackupRuntimeRefused):
        media.prove()


def test_removing_current_selection_argument_has_an_executed_falsifier(media):
    source = inspect.getsource(maintenance.prove)
    old = 'allow_continuity=False, base_backup=None'
    assert source.count(old) == 1
    namespace = vars(maintenance).copy()
    exec(compile(source.replace(old, 'allow_continuity=False, base_backup=base_backup'),
                 '<removed-current-selection>', 'exec'), namespace)
    successor = 'base-20261110T235957Z'
    shutil.copytree(media.directory, media.base_root/successor)
    media.select(successor)
    with pytest.raises(authority.BackupIntegritySelectionMoved):
        media.prove()
    # The exact omission incorrectly admits the obsolete requested base. The
    # real final-selection contract above would therefore fail under mutation.
    mutant = namespace['prove'](media.conn, base_backup=media.base,
        system_identifier=media.system, wal_segment_bytes=SIZE,
        observed_frontier=media.end, wait_seconds=0)
    assert mutant.base_backup == media.base
