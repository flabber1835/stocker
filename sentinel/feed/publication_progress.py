"""Optional live phase observation for a registered closing-data producer."""
from __future__ import annotations

import os
from contextlib import suppress
from queue import Empty, Queue
import re
from threading import Thread

from sentinel.feed.publication import CORPUS_LOCK_KEY


PHASES = {
    'R': 'REFERENCES', 'P': 'PRICES', 'B': 'BUILDING', 'I': 'IDENTITY', 'N': 'NORMALIZATION',
    'S': 'SEALING', 'V': 'VALIDATION', 'C': 'CORROBORATION', 'U': 'PUBLICATION',
}
_TAG = re.compile(r'sf1:([0-9a-f]{32}):([RPBINSVCU]):([1-9][0-9]{0,9}):(-|[0-9]{1,12})')
_ATOMIC_PHASES = {'IDENTITY', 'NORMALIZATION', 'SEALING'}
_WAITS = {'Lock': 'DATABASE_LOCK', 'LWLock': 'DATABASE_LOCK',
          'IO': 'DATABASE_IO', 'BufferPin': 'DATABASE_SYNC', 'IPC': 'DATABASE_SYNC'}

# This lateral read sees no SQL text or parameters. The original job lease and
# its registration remain visible even while its candidate transaction is open.
OBSERVATION_SQL = f"""SELECT CASE WHEN count(*)=1 THEN jsonb_agg(proof)->0 END AS proof
    FROM (
        SELECT jsonb_build_object('tag',t.application_name,
            'atomic',coalesce(a.backend_xid::text=j.xmax::text AND EXISTS (
                SELECT 1 FROM pg_locks l WHERE l.pid=a.pid AND l.locktype='advisory'
                    AND l.granted AND l.mode='ExclusiveLock' AND l.objsubid=1
                    AND ((l.classid::bigint << 32)|l.objid::bigint)={CORPUS_LOCK_KEY}),false),
            'wait',CASE WHEN a.state='active' THEN a.wait_event_type END) AS proof
        FROM pg_stat_activity t JOIN pg_stat_activity a
            ON a.pid::text=split_part(t.application_name,':',4)
            AND a.datid=t.datid AND a.usename=t.usename AND a.pid<>t.pid
            AND a.backend_start<=t.backend_start AND a.backend_type='client backend'
            AND a.state IN ('active','idle','idle in transaction')
        WHERE j.state IN ('ACQUIRING','STAGING','VALIDATING','READY')
            AND t.datname=current_database() AND t.usename=current_user
            AND t.backend_type='client backend'
            AND t.state IN ('active','idle') AND t.backend_start>=j.created_at
            AND split_part(t.application_name,':',1)='sf1'
            AND split_part(t.application_name,':',2)=replace(j.owner::text,'-','')
        LIMIT 2
    ) matches"""


def read_phase(proof, owner):
    """Return only a closed live observation, independently of readiness."""
    if not isinstance(proof, dict) or set(proof) != {'tag', 'atomic', 'wait'}:
        return None
    tag = _TAG.fullmatch(proof['tag']) if isinstance(proof['tag'], str) else None
    if tag is None or tag[1] != str(owner).replace('-', '') or type(proof['atomic']) is not bool:
        return None
    phase = PHASES[tag[2]]
    if phase in _ATOMIC_PHASES and not proof['atomic']:
        return None
    wait = proof['wait']
    if wait is not None and not isinstance(wait, str):
        return None
    return dict(phase=phase, rows=None if tag[4] == '-' else int(tag[4]), wait=_WAITS.get(wait))


class PublisherProgress:
    """A single latest-only sender. No telemetry I/O runs on the writer thread."""

    @classmethod
    def for_worker(cls, conn, owner):
        dsn = os.environ.get('SENTINEL_DATABASE_URL')
        if os.environ.get('SENTINEL_FEED_SERVICE_MODE') != 'SHADOW' or not dsn:
            return None
        with suppress(Exception):
            writer = conn.info.backend_pid
            if type(writer) is not int or not 0 < writer < 2**31:
                return None
            publisher = cls(dsn, owner, writer)
            Thread(target=publisher._send, name='closing-feed-progress', daemon=True).start()
            return publisher
        return None

    def __init__(self, dsn, owner, writer):
        self.dsn, self.owner, self.writer = dsn, owner.replace('-', ''), writer
        self.updates = Queue(maxsize=1)

    def _latest(self, tag):
        try:
            self.updates.get_nowait()
        except Empty:
            pass
        self.updates.put_nowait(tag)

    def publish(self, phase, rows=None):
        if phase not in PHASES or rows is not None and (type(rows) is not int or not 0 <= rows < 10**12):
            return
        count = '-' if rows is None else str(rows)
        tag = f'sf1:{self.owner}:{phase}:{self.writer}:{count}'
        if _TAG.fullmatch(tag):
            self._latest(tag)

    def close(self):
        self._latest(None)

    def _send(self):
        from sentinel.feed import store

        conn = None
        try:
            conn = store.connect(self.dsn, connect_timeout=2, statement_timeout_ms=250)
            conn.autocommit = True
            while (tag := self.updates.get()) is not None:
                conn.execute("SELECT set_config('application_name',%s,false)", (tag,))
        except Exception:
            # Driver exceptions belong to the optional connection only.
            pass
        finally:
            if conn is not None:
                with suppress(Exception):
                    conn.close()
