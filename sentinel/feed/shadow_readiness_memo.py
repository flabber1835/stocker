"""Bounded raw-input memo shared only by an owned SHADOW verifier's workers."""

from contextvars import ContextVar
from datetime import datetime, timezone
import hmac
import json
from multiprocessing import get_context
import os
import time
from uuid import uuid4

from sentinel import receipt_authentication
from sentinel.feed.rolling_contract import canonical_json, digest


current_memo = ContextVar('shadow_readiness_memo', default=None)
SCRUB_SECONDS = 20 * 60
MAX_BYTES = 128 * 1024
_PURPOSE = 'sentinel.shadow-verifier-readiness-material/1'
_RELATIONS = (
    'sentinel_corpus_publications', 'sentinel_operational_snapshots',
    'sentinel_snapshot_jobs',
    'sentinel_price_candidates', 'sentinel_candidate_layouts',
    'sentinel_candidate_blocks', 'sentinel_normalized_blocks',
    'sentinel_snapshot_bars', 'sentinel_snapshot_benchmarks',
    'sentinel_snapshot_evidence', 'sentinel_snapshot_validations',
    'sentinel_operational_snapshot_validations', 'sentinel_snapshot_retirements',
)


def _clock():
    return time.monotonic(), datetime.now(timezone.utc).timestamp()


def _age_current(started, now):
    return (len(started) == len(now) == 2
            and all(0 <= end - start < SCRUB_SECONDS for start, end in zip(started, now)))


def _witness(conn, pub, *, financial_pin=False):
    from sentinel import operational_ddl_epoch
    from sentinel.feed import normalized_layout

    db = conn.execute("SELECT current_setting('transaction_isolation'),"
        "current_setting('transaction_read_only'),current_setting('session_replication_role'),"
        "to_regclass('public.sentinel_operational_ddl_epoch') IS NOT NULL,"
        "s.system_identifier::text,d.oid::text,pg_postmaster_start_time()::text,"
        "floor(pg_snapshot_xmax(pg_current_snapshot())::text::numeric/4294967296)::bigint "
        "FROM pg_control_system() s JOIN pg_database d ON d.datname=current_database()").fetchone()
    if db is None or db[2:4] != ('origin', True):
        return None
    if financial_pin:
        from sentinel.feed import readiness_scope
        pin = readiness_scope.capture(conn)
        if pin is None or pin.publication != digest(pub.to_dict()):
            return None
    elif db[:2] != ('repeatable read', 'on'):
        return None
    if not normalized_layout.available(conn):
        return None
    ddl = operational_ddl_epoch.current(conn)
    physical = conn.execute(
        'SELECT c.relname,c.oid::text,pg_relation_filenode(c.oid)::text,c.reltoastrelid::text,'
        'pg_relation_filenode(c.reltoastrelid)::text FROM pg_class c '
        "WHERE c.relnamespace='public'::regnamespace AND c.relname=ANY(%s) "
        'AND to_regclass(c.relname)=c.oid ORDER BY c.relname', (list(_RELATIONS),)).fetchall()
    if len(physical) != len(_RELATIONS):
        return None
    key = pub.evidence['rolling_snapshot']
    binding = conn.execute('''
        SELECT c.snapshot_id,jsonb_array_length(c.session_axis),
               ARRAY[c.reference_sha256,c.source_evidence_sha256,o.validation_sha256,v.validation_sha256],
               ARRAY[p.xmin::text,p.ctid::text,s.xmin::text,s.ctid::text,j.xmin::text,j.ctid::text,
                     c.xmin::text,c.ctid::text,l.xmin::text,l.ctid::text,
                     o.xmin::text,o.ctid::text,v.xmin::text,v.ctid::text]
        FROM sentinel_corpus_publications p
        JOIN sentinel_operational_snapshots s ON s.publication_version=p.version
        JOIN sentinel_snapshot_jobs j USING(job_id)
        JOIN sentinel_price_candidates c ON c.candidate_id=s.candidate_id
        JOIN sentinel_candidate_layouts l ON l.candidate_id=c.candidate_id
        JOIN sentinel_operational_snapshot_validations o ON o.candidate_id=c.candidate_id
        JOIN sentinel_snapshot_validations v ON v.candidate_id=c.candidate_id
        WHERE p.version=%s AND c.candidate_id=%s AND l.snapshot_id=c.snapshot_id
          AND c.manifest->>'provider'='ALPACA_OPENFIGI' AND j.state='PUBLISHED'
          AND o.validation_sha256=s.validation_sha256
          AND NOT EXISTS (SELECT 1 FROM sentinel_snapshot_retirements r WHERE r.candidate_id=c.candidate_id)
          AND NOT EXISTS (SELECT 1 FROM sentinel_snapshot_bars b WHERE b.candidate_id=c.candidate_id)
          AND NOT EXISTS (SELECT 1 FROM sentinel_snapshot_benchmarks b WHERE b.candidate_id=c.candidate_id)
        ''', (pub.version, key['candidate_id'])).fetchone()
    if binding is None or binding[0] != key['snapshot_id'] or not 1 <= binding[1] <= 426:
        return None
    evidence = conn.execute('''
        SELECT evidence_sha256,xmin::text,ctid::text FROM sentinel_snapshot_evidence
        WHERE evidence_sha256=ANY(%s) AND (payload IS NOT NULL OR canonical_payload IS NOT NULL)
        ORDER BY evidence_sha256
        ''', (binding[2],)).fetchall()
    blocks = conn.execute('''
        SELECT r.kind,r.session::text,r.block_sha256,r.xmin::text,r.ctid::text,b.xmin::text,b.ctid::text
        FROM sentinel_candidate_blocks r JOIN sentinel_normalized_blocks b USING(block_sha256)
        WHERE r.candidate_id=%s AND b.canonical_payload IS NOT NULL ORDER BY r.kind,r.session LIMIT 853
        ''', (key['candidate_id'],)).fetchall()
    if len(evidence) != len(set(binding[2])) or len(blocks) != 2 * binding[1]:
        return None
    native = db
    if financial_pin:
        from sentinel import prepared_opening_material
        epoch = prepared_opening_material.version_epoch(conn, (binding[3], evidence, blocks))
        if epoch is None:
            return None
        native = [db[2:], epoch]
    return digest([native, ddl, physical, pub.to_dict(), binding, evidence, blocks,
                   os.environ.get('SENTINEL_GIT_COMMIT'), os.environ.get('SENTINEL_RUNTIME_IMAGE_DIGEST')])


class ReadinessMemo:
    """One signed slot. Only complete writes can authenticate after worker loss."""

    def __init__(self):
        self.owner = uuid4().hex
        self.slot = get_context('spawn').RawArray('B', MAX_BYTES)

    def _signature(self, value):
        return receipt_authentication.sign({'purpose': _PURPOSE, 'owner': self.owner, 'value': value})

    def _read(self, subject, now):
        from sentinel.core.rolling_inputs import ReadinessInputs
        from sentinel.feed.rolling_contract import CanonicalBenchmark

        size = int.from_bytes(bytes(self.slot[:4]), 'big')
        if not 0 < size <= MAX_BYTES - 4:
            return None
        try:
            value, signature = json.loads(bytes(self.slot[4:4 + size]))
            if (value['subject'] != subject or not _age_current(value['started'], now)
                    or not hmac.compare_digest(signature, self._signature(value))):
                return None
            facts = value['facts']
            facts['benchmarks'] = tuple(CanonicalBenchmark.model_validate(row) for row in facts['benchmarks'])
            return ReadinessInputs(**facts)
        except (KeyError, TypeError, ValueError, OverflowError):
            return None

    def _store(self, subject, started, material):
        from dataclasses import asdict

        facts = asdict(material)
        facts['benchmarks'] = [row.model_dump(mode='json') for row in material.benchmarks]
        value = dict(subject=subject, started=started, facts=facts)
        try:
            raw = canonical_json([value, self._signature(value)]).encode('ascii')
        except (TypeError, ValueError):
            return
        if len(raw) <= MAX_BYTES - 4:
            self.slot[:4] = b'\0' * 4
            self.slot[4:4 + len(raw)] = raw
            self.slot[:4] = len(raw).to_bytes(4, 'big')

    def measure(self, conn, pub, load):
        started = _clock()
        subject = _witness(conn, pub)
        if subject is None:
            return load()
        cached = self._read(subject, _clock())
        if cached is not None:
            return cached
        material = load()
        if _age_current(started, _clock()) and _witness(conn, pub) == subject:
            self._store(subject, started, material)
        return material
