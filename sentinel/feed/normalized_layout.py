"""Immutable shared session payloads behind unchanged logical snapshot identities.

All writes belong to the caller's existing transaction and publication lease.
The legacy candidate tables stay intact. Only byte-identical complete session
blocks can share physical storage; a block never supplies observation authority.
"""
from __future__ import annotations

import hashlib
import json
from typing import Literal

from sentinel.feed.rolling_contract import CanonicalBar, CanonicalBenchmark, canonical_json, digest
from sentinel.transaction_contract import TransactionPort, borrow
from sentinel.feed import read_contract, rolling_work
from sentinel.feed.read_contract import _BAR_VIEW, _BENCHMARK_VIEW

SCHEMA = 'sentinel.normalized-session-block/1'
LAYOUT_SCHEMA = 'sentinel.normalized-snapshot-layout/1'
MAX_SESSION_ROWS = 100_000
MAX_SESSION_BYTES = 64 * 1024 * 1024
extension_tables = frozenset({'sentinel_normalized_blocks', 'sentinel_candidate_blocks',
                              'sentinel_candidate_layouts'})
extension_views = frozenset({'sentinel_candidate_bars', 'sentinel_candidate_benchmarks'})
extension_functions = frozenset({'sentinel_normalized_immutable',
    'sentinel_normalized_reference_guard', 'sentinel_normalized_legacy_guard',
    'sentinel_normalized_layout_guard'})
extension_trigger_pairs = frozenset({
    *((table, name) for table in extension_tables for name in ('normalized_immutable','normalized_no_truncate')),
    ('sentinel_candidate_blocks','normalized_reference_guard'),
    ('sentinel_candidate_layouts','normalized_layout_guard'),
    ('sentinel_snapshot_bars','normalized_legacy_guard'),
    ('sentinel_snapshot_benchmarks','normalized_legacy_guard'),
})
extension_triggers = frozenset(name for _table,name in extension_trigger_pairs)


class LayoutRefused(ValueError):
    pass


_GUARD = """CREATE OR REPLACE FUNCTION sentinel_normalized_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_TABLE_NAME='sentinel_normalized_blocks' AND TG_OP='UPDATE'
      AND (to_jsonb(NEW)-'canonical_payload')=(to_jsonb(OLD)-'canonical_payload') THEN
    IF OLD.canonical_payload IS NULL AND NEW.canonical_payload IS NOT NULL THEN RETURN NEW; END IF;
    IF NEW.canonical_payload IS NULL THEN
      PERFORM sentinel_retention_locks();
      IF NOT EXISTS(SELECT 1 FROM sentinel_candidate_blocks b WHERE b.block_sha256=OLD.block_sha256
          AND NOT EXISTS(SELECT 1 FROM sentinel_snapshot_retirements r WHERE r.candidate_id=b.candidate_id))
        THEN RETURN NEW; END IF;
    END IF;
  END IF;
  RAISE EXCEPTION 'normalized layout evidence is immutable';
END $$"""
_REF_GUARD = """CREATE OR REPLACE FUNCTION sentinel_normalized_reference_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE c JSONB; b RECORD;
BEGIN
  SELECT manifest INTO c FROM sentinel_price_candidates WHERE candidate_id=NEW.candidate_id FOR UPDATE;
  IF NOT FOUND OR c IS NOT NULL THEN RAISE EXCEPTION 'normalized references require an owned unsealed candidate'; END IF;
  SELECT * INTO b FROM sentinel_normalized_blocks WHERE block_sha256=NEW.block_sha256 FOR SHARE;
  IF NOT FOUND OR b.canonical_payload IS NULL OR b.kind<>NEW.kind OR b.session<>NEW.session THEN
    RAISE EXCEPTION 'normalized reference does not bind a complete session payload'; END IF;
  IF EXISTS(SELECT 1 FROM sentinel_snapshot_bars WHERE candidate_id=NEW.candidate_id)
      OR EXISTS(SELECT 1 FROM sentinel_snapshot_benchmarks WHERE candidate_id=NEW.candidate_id) THEN
    RAISE EXCEPTION 'legacy and shared candidate payloads cannot mix'; END IF;
  RETURN NEW;
END $$"""
_LEGACY_GUARD = """CREATE OR REPLACE FUNCTION sentinel_normalized_legacy_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF EXISTS(SELECT 1 FROM sentinel_candidate_blocks WHERE candidate_id=NEW.candidate_id) THEN
    RAISE EXCEPTION 'legacy and shared candidate payloads cannot mix'; END IF;
  RETURN NEW;
END $$"""
_LAYOUT_GUARD = """CREATE OR REPLACE FUNCTION sentinel_normalized_layout_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE c RECORD; refs JSONB;
BEGIN
  SELECT snapshot_id,manifest INTO c FROM sentinel_price_candidates WHERE candidate_id=NEW.candidate_id FOR UPDATE;
  SELECT jsonb_agg(jsonb_build_object('kind',kind,'session',session::text,'block_sha256',block_sha256)
      ORDER BY kind,session) INTO refs FROM sentinel_candidate_blocks WHERE candidate_id=NEW.candidate_id;
  IF NOT FOUND OR c.manifest IS NULL OR c.snapshot_id<>NEW.snapshot_id
      OR refs IS NULL OR refs<>NEW.block_references OR NEW.layout->>'schema'<>'sentinel.normalized-snapshot-layout/1'
      OR NEW.layout->>'snapshot_id'<>NEW.snapshot_id OR NEW.layout->'references'<>refs
      OR NEW.layout->>'candidate_id'<>NEW.candidate_id::text THEN
    RAISE EXCEPTION 'normalized layout does not bind the sealed logical snapshot'; END IF;
  RETURN NEW;
END $$"""


DDL = (
    """CREATE TABLE sentinel_normalized_blocks (
        block_sha256 TEXT PRIMARY KEY CHECK(block_sha256 ~ '^[0-9a-f]{64}$'),
        kind TEXT NOT NULL CHECK(kind IN ('BARS','BENCHMARKS')),
        session DATE NOT NULL, normalization_version TEXT NOT NULL, calendar_version TEXT NOT NULL,
        row_count INTEGER NOT NULL CHECK(row_count BETWEEN 1 AND 100000),
        canonical_payload TEXT CHECK(canonical_payload IS NULL OR
          (octet_length(canonical_payload)<=67108864 AND encode(sha256(convert_to(canonical_payload,'UTF8')),'hex')=block_sha256
           AND canonical_payload::jsonb->>'schema'='sentinel.normalized-session-block/1'
           AND canonical_payload::jsonb->>'kind'=kind AND (canonical_payload::jsonb->>'session')::date=session
           AND canonical_payload::jsonb->>'normalization_version'=normalization_version
           AND canonical_payload::jsonb->>'calendar_version'=calendar_version
           AND jsonb_array_length(canonical_payload::jsonb->'rows')=row_count)))""",
    """CREATE TABLE sentinel_candidate_blocks (
        candidate_id UUID NOT NULL REFERENCES sentinel_price_candidates,
        kind TEXT NOT NULL CHECK(kind IN ('BARS','BENCHMARKS')), session DATE NOT NULL,
        block_sha256 TEXT NOT NULL REFERENCES sentinel_normalized_blocks,
        PRIMARY KEY(candidate_id,kind,session))""",
    'CREATE INDEX sentinel_candidate_blocks_payload ON sentinel_candidate_blocks(block_sha256)',
    """CREATE TABLE sentinel_candidate_layouts (
        candidate_id UUID PRIMARY KEY REFERENCES sentinel_price_candidates,
        snapshot_id TEXT NOT NULL CHECK(snapshot_id ~ '^[0-9a-f]{64}$'),
        block_references JSONB NOT NULL, layout JSONB NOT NULL,
        layout_sha256 TEXT NOT NULL CHECK(layout_sha256 ~ '^[0-9a-f]{64}$'),
        canonical_layout TEXT NOT NULL CHECK(canonical_layout::jsonb=layout
            AND encode(sha256(convert_to(canonical_layout,'UTF8')),'hex')=layout_sha256))""",
    _GUARD, _REF_GUARD, _LEGACY_GUARD, _LAYOUT_GUARD,
    *(f'CREATE TRIGGER normalized_immutable BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION sentinel_normalized_immutable()'
      for table in sorted(extension_tables)),
    *(f'CREATE TRIGGER normalized_no_truncate BEFORE TRUNCATE ON {table} FOR EACH STATEMENT EXECUTE FUNCTION sentinel_normalized_immutable()'
      for table in sorted(extension_tables)),
    'CREATE TRIGGER normalized_reference_guard BEFORE INSERT ON sentinel_candidate_blocks FOR EACH ROW EXECUTE FUNCTION sentinel_normalized_reference_guard()',
    'CREATE TRIGGER normalized_layout_guard BEFORE INSERT ON sentinel_candidate_layouts FOR EACH ROW EXECUTE FUNCTION sentinel_normalized_layout_guard()',
    *(f'CREATE TRIGGER normalized_legacy_guard BEFORE INSERT ON {table} FOR EACH ROW EXECUTE FUNCTION sentinel_normalized_legacy_guard()'
      for table in ('sentinel_snapshot_bars','sentinel_snapshot_benchmarks')),
    _BAR_VIEW, _BENCHMARK_VIEW,
)


def available(conn):
    """Exact optional contract; installed-component loss cannot become legacy."""
    return require_schema(conn,allow_absent=True)


def read_table(conn, kind: Literal['BARS','BENCHMARKS']):
    if kind not in ('BARS','BENCHMARKS'):
        raise LayoutRefused('NORMALIZED_LAYOUT_KIND_INVALID')
    return read_contract.table_name(kind,shared=available(conn))


def candidate_query(conn, statement):
    """One physical-read owner; parameters and economic predicates stay intact."""
    return read_contract.route(statement,shared=available(conn))


def require_schema(conn, *, allow_absent=False):
    """SELECT-only exact catalog witness; no runtime scratch installation."""
    from sentinel import operational_catalog
    return operational_catalog.require_extension(conn, __name__, allow_absent=allow_absent)


def install(conn: TransactionPort):
    conn = borrow(conn)
    if require_schema(conn, allow_absent=True):
        return
    for statement in DDL:
        conn.execute(statement)
    require_schema(conn)


def _block(kind, session, rows, normalization, calendar):
    model = CanonicalBar if kind == 'BARS' else CanonicalBenchmark
    material = [model.model_validate(row.model_dump() if isinstance(row, model) else row)
                for row in rows]
    if not material or len(material) > MAX_SESSION_ROWS or any(str(row.session) != session for row in material):
        raise LayoutRefused('NORMALIZED_SESSION_BLOCK_AXIS_CHANGED')
    material.sort(key=lambda row: row.security_id if kind == 'BARS' else str(row.session))
    keys = [row.security_id if kind == 'BARS' else str(row.session) for row in material]
    if len(set(keys)) != len(keys):
        raise LayoutRefused('NORMALIZED_SESSION_BLOCK_DUPLICATE')
    value = dict(schema=SCHEMA,kind=kind,session=session,normalization_version=normalization,
                 calendar_version=calendar,rows=[row.model_dump(mode='json') for row in material])
    encoded = canonical_json(value)
    if len(encoded) > MAX_SESSION_BYTES:
        raise LayoutRefused('NORMALIZED_SESSION_BLOCK_LIMIT')
    return value, encoded, hashlib.sha256(encoded.encode('ascii')).hexdigest()


class SessionBlockWriter:
    """One bounded session in memory, no complete duplicate candidate window."""
    def __init__(self, conn, candidate_id, *, normalization_version, calendar_version):
        require_schema(conn)
        self.conn, self.candidate_id = borrow(conn), candidate_id
        self.normalization, self.calendar = normalization_version, calendar_version
        self.session, self.rows, self.references = None, [], []
        self.reused_blocks = 0

    def _store(self, kind, session, rows):
        value, encoded, sha = _block(kind, session, rows, self.normalization, self.calendar)
        inserted = self.conn.execute('INSERT INTO sentinel_normalized_blocks VALUES(%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING block_sha256',
            (sha,kind,session,self.normalization,self.calendar,len(value['rows']),encoded)).fetchone()
        row = self.conn.execute('SELECT canonical_payload FROM sentinel_normalized_blocks WHERE block_sha256=%s FOR UPDATE', (sha,)).fetchone()
        if row is None:
            raise LayoutRefused('NORMALIZED_SESSION_BLOCK_MISSING')
        if row[0] is None:
            self.conn.execute('UPDATE sentinel_normalized_blocks SET canonical_payload=%s WHERE block_sha256=%s', (encoded,sha))
        elif row[0] != encoded or hashlib.sha256(row[0].encode('ascii')).hexdigest() != sha:
            raise LayoutRefused('NORMALIZED_SESSION_BLOCK_CONTENT_CHANGED')
        elif not inserted:
            self.reused_blocks += 1
        self.conn.execute('INSERT INTO sentinel_candidate_blocks VALUES(%s,%s,%s,%s)',
            (self.candidate_id,kind,session,sha))
        self.references.append(dict(kind=kind,session=session,block_sha256=sha))

    def write_bars(self, rows, *, progress=None):
        count = 0
        for raw in rows:
            row = CanonicalBar.model_validate(raw.model_dump() if isinstance(raw, CanonicalBar) else raw)
            day = str(row.session)
            if self.session is not None and day < self.session:
                raise LayoutRefused('NORMALIZED_SESSION_ORDER_CHANGED')
            if self.session is not None and day != self.session:
                self._store('BARS',self.session,self.rows)
                self.rows = []
            self.session = day
            self.rows.append(row)
            count += 1
            if len(self.rows) > MAX_SESSION_ROWS:
                raise LayoutRefused('NORMALIZED_SESSION_BLOCK_LIMIT')
            if progress is not None and count % 5000 == 0:
                progress(count)
        if self.rows:
            self._store('BARS',self.session,self.rows)
            self.rows, self.session = [], None
        if progress is not None and count % 5000:
            progress(count)
        return count

    def write_benchmarks(self, rows):
        for row in rows:
            rolling_work.checkpoint()
            self._store('BENCHMARKS',str(row.session),[row])
            rolling_work.checkpoint()


def seal_layout(conn, candidate_id, manifest):
    refs = conn.execute('SELECT kind,session,block_sha256 FROM sentinel_candidate_blocks '
        'WHERE candidate_id=%s ORDER BY kind,session', (candidate_id,)).fetchall()
    if not refs:
        return None
    _require_references(conn, refs, manifest)
    references = [dict(kind=kind,session=str(day),block_sha256=sha) for kind,day,sha in refs]
    value = dict(schema=LAYOUT_SCHEMA,candidate_id=str(candidate_id),snapshot_id=manifest.snapshot_id,references=references)
    encoded = canonical_json(value)
    conn.execute('INSERT INTO sentinel_candidate_layouts VALUES(%s,%s,%s::jsonb,%s::jsonb,%s,%s)',
        (candidate_id,manifest.snapshot_id,canonical_json(references),encoded,digest(value),encoded))
    return value


def require_layout(conn, candidate_id, manifest):
    if not available(conn):
        return
    refs = conn.execute('SELECT kind,session,block_sha256 FROM sentinel_candidate_blocks WHERE candidate_id=%s ORDER BY kind,session', (candidate_id,)).fetchall()
    record = conn.execute('SELECT layout,layout_sha256 FROM sentinel_candidate_layouts WHERE candidate_id=%s', (candidate_id,)).fetchone()
    if not refs and record is None:
        return  # Authenticated legacy physical generation.
    _require_references(conn, refs, manifest)
    expected = dict(schema=LAYOUT_SCHEMA,candidate_id=str(candidate_id),snapshot_id=manifest.snapshot_id,
        references=[dict(kind=kind,session=str(day),block_sha256=sha) for kind,day,sha in refs])
    if record is None or record[0] != expected or record[1] != digest(expected):
        raise LayoutRefused('NORMALIZED_LAYOUT_BINDING_CHANGED')


def _require_references(conn, refs, manifest):
    expected = [(kind,str(day)) for kind in ('BARS','BENCHMARKS') for day in manifest.window.sessions]
    if [(kind,str(day)) for kind,day,_sha in refs] != expected:
        raise LayoutRefused('NORMALIZED_LAYOUT_AXIS_CHANGED')
    blocks = conn.execute('SELECT block_sha256,kind,session,normalization_version,calendar_version '
        'FROM sentinel_normalized_blocks WHERE block_sha256=ANY(%s)',
        ([sha for _kind,_day,sha in refs],)).fetchall()
    headers = {sha:(kind,str(day),normalization,calendar) for sha,kind,day,normalization,calendar in blocks}
    for kind,day,sha in refs:
        if headers.get(sha) != (kind,str(day),manifest.normalization_version,manifest.calendar_version):
            raise LayoutRefused('NORMALIZED_LAYOUT_BLOCK_HEADER_CHANGED')


def release_retired(conn, *, limit=32):
    """Payload retirement only; identities/layout references remain immutable."""
    rows = conn.execute('SELECT b.block_sha256 FROM sentinel_normalized_blocks b WHERE canonical_payload IS NOT NULL '
        'AND NOT EXISTS(SELECT 1 FROM sentinel_candidate_blocks r WHERE r.block_sha256=b.block_sha256 '
        'AND NOT EXISTS(SELECT 1 FROM sentinel_snapshot_retirements gone WHERE gone.candidate_id=r.candidate_id)) '
        'ORDER BY b.block_sha256 LIMIT %s', (limit,)).fetchall()
    for (sha,) in rows:
        conn.execute('UPDATE sentinel_normalized_blocks SET canonical_payload=NULL WHERE block_sha256=%s', (sha,))
    return len(rows)
