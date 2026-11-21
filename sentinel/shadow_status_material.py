"""Private canonical checkpoint material for the read-only SHADOW observer."""
from contextvars import ContextVar
from datetime import datetime, timezone
import hashlib
import hmac
import json
from multiprocessing import get_context
import pickle
import time
from uuid import uuid4

from sentinel import receipt_authentication

current_memo = ContextVar('shadow_status_material', default=None)
MAX_BYTES = 16 * 1024 * 1024
HEADER_BYTES = 4096
SCRUB_SECONDS = 20 * 60
PURPOSE = 'sentinel.shadow-status-material/1'


def _clock():
    return time.monotonic(), datetime.now(timezone.utc).timestamp()


def _current(started, now):
    return (len(started) == len(now) == 2
            and all(0 <= end-start < SCRUB_SECONDS for start, end in zip(started, now)))


def _witness(conn, key):
    from sentinel import operational_ddl_epoch
    from sentinel.feed import readiness_scope

    pin = readiness_scope.capture(conn)
    if pin is None or pin.owner is not conn or pin.backend_pid != conn.info.backend_pid:
        return None
    db = conn.execute(
        "SELECT current_setting('transaction_isolation'),current_setting('transaction_read_only'),"
        "current_setting('session_replication_role'),pg_current_xact_id_if_assigned() IS NULL,"
        "to_regclass('public.sentinel_operational_ddl_epoch') IS NOT NULL,"
        "s.system_identifier::text,d.oid::text,pg_postmaster_start_time()::text,"
        "pg_snapshot_xmax(pg_current_snapshot())::text::numeric "
        "FROM pg_control_system() s JOIN pg_database d ON d.datname=current_database()"
    ).fetchone()
    if db is None or db[:5] != ('repeatable read', 'on', 'origin', True, True):
        return None
    ddl = operational_ddl_epoch.current(conn)
    relation = conn.execute(
        "SELECT c.oid,pg_relation_filenode(c.oid),c.reltoastrelid,"
        "pg_relation_filenode(c.reltoastrelid) FROM pg_class c "
        "WHERE c.oid='public.sentinel_processed_sessions'::regclass"
    ).fetchone()
    rows = conn.execute(
        "SELECT cursor_name,session,tableoid,xmin::text,ctid::text "
        "FROM public.sentinel_processed_sessions ORDER BY cursor_name LIMIT 1025"
    ).fetchall()
    low_xmax = int(db[-1]) % 4294967296
    if (relation is None or not relation[1] or len(rows) > 1024
            or any(int(row[3]) >= low_xmax for row in rows)):
        return None
    readiness_scope.require_token(conn, pin)
    # Private equality witness only; it is never published or used as authority.
    facts = (db[:-1], int(db[-1])//4294967296, ddl, relation, rows, pin.publication, key)
    return hashlib.sha256(pickle.dumps(facts, protocol=5)).hexdigest()


class StatusMaterialMemo:
    """One signed slot; complete canonical loads are its only producer."""

    def __init__(self):
        self.owner = uuid4().hex
        self.slot = get_context('spawn').RawArray('B', MAX_BYTES)

    def _signature(self, value):
        return receipt_authentication.sign({'purpose': PURPOSE, 'owner': self.owner, 'value': value})

    def _read(self, subject, now):
        memory = memoryview(self.slot).cast('B')
        size = int.from_bytes(memory[:4], 'big')
        if not 0 < size <= MAX_BYTES-8:
            return None
        head_size = int.from_bytes(memory[4:8], 'big')
        if not 0 < head_size <= min(HEADER_BYTES, size):
            return None
        try:
            value, signature = json.loads(bytes(memory[8:8+head_size]))
            if (set(value) != {'subject', 'started', 'size', 'sha256'}
                    or value['subject'] != subject or not _current(value['started'], now)
                    or value['size'] != size-head_size
                    or not hmac.compare_digest(signature, self._signature(value))):
                return None
            raw = bytes(memory[8+head_size:8+size])
            if not hmac.compare_digest(value['sha256'], hashlib.sha256(raw).hexdigest()):
                return None
            # Only this owner's just-authenticated canonical private bytes enter
            # pickle. Neither disk, a database payload nor another owner can seed it.
            return pickle.loads(raw)
        except (KeyError, TypeError, ValueError, OverflowError, EOFError,
                pickle.UnpicklingError, AttributeError, ImportError):
            return None

    def _store(self, subject, started, material):
        raw = pickle.dumps(material, protocol=5)
        if len(raw) > MAX_BYTES-HEADER_BYTES-8:
            return
        value = dict(subject=subject, started=started, size=len(raw),
                     sha256=hashlib.sha256(raw).hexdigest())
        head = json.dumps([value, self._signature(value)], sort_keys=True,
                          separators=(',', ':'), allow_nan=False).encode('ascii')
        if len(head) > HEADER_BYTES:
            return
        memory = memoryview(self.slot).cast('B')
        memory[:4] = b'\0'*4
        memory[4:8] = len(head).to_bytes(4, 'big')
        memory[8:8+len(head)] = head
        memory[8+len(head):8+len(head)+len(raw)] = raw
        memory[:4] = (len(head)+len(raw)).to_bytes(4, 'big')

    def measure(self, conn, key, load):
        started = _clock()
        subject = _witness(conn, key)
        if subject is None:
            return load()
        cached = self._read(subject, _clock())
        if cached is not None:
            return cached
        material = load()
        if _current(started, _clock()) and _witness(conn, key) == subject:
            self._store(subject, started, material)
        return material
