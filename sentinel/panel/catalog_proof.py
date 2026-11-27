"""Reuse only previously compared dashboard definitions under native DDL witnesses."""
from dataclasses import dataclass
import hashlib
import importlib
import os
from threading import Lock
import time

import psycopg

from sentinel import operational_catalog as catalog


_COMPONENTS = frozenset({
    'sentinel.operational_schema', 'sentinel.operational_ddl_epoch',
    'sentinel.panel.operational_schema',
})
_SECONDS = 30
_LOCK = Lock()


@dataclass(frozen=True)
class Proof:
    start: float
    wall_start: float
    identity: tuple

    def current(self):
        return (self.start <= time.monotonic() < self.start + _SECONDS
                and self.wall_start <= time.time() < self.wall_start + _SECONDS)


# At most one recent comparison per component per process.
_verified: dict[str, Proof] = {}


def _identity(conn, module_name):
    meta = conn.execute("""
        SELECT current_setting('transaction_isolation'),pg_current_xact_id_if_assigned(),
               current_schemas(true),current_setting('session_replication_role'),
               to_regclass('public.sentinel_operational_ddl_epoch')::oid,
               has_function_privilege('pg_catalog.pg_control_system()','EXECUTE'),
               has_table_privilege(to_regclass('public.sentinel_operational_ddl_epoch'),'SELECT'),
               d.oid,d.datname,pg_postmaster_start_time(),
               current_user,session_user,current_setting('quote_all_identifiers'),
               current_setting('standard_conforming_strings'),
               floor(pg_snapshot_xmax(pg_current_snapshot())::text::numeric/4294967296)
        FROM pg_catalog.pg_database d WHERE d.datname=current_database()
        """).fetchone()
    if (meta[0] not in ('repeatable read', 'serializable') or meta[1] is not None
            or meta[2] != ['pg_catalog', 'public'] or meta[3] != 'origin'
            or meta[4] is None or not meta[5] or not meta[6]):
        return None
    guard = conn.execute("""
        SELECT e.incarnation,e.epoch,e.tableoid,pg_relation_filenode(e.tableoid),
               e.xmin::text,e.ctid::text,t.oid,t.xmin::text,t.ctid::text,
               p.oid,p.xmin::text,p.ctid::text,s.system_identifier,
               to_regprocedure('pg_catalog.gen_random_uuid()')::oid,
               to_regoperator('pg_catalog.=(integer,integer)')::oid,
               to_regoperator('pg_catalog.>=(integer,integer)')::oid,
               to_regoperator('pg_catalog.<=(integer,integer)')::oid,
               to_regoperator('pg_catalog.>=(bigint,integer)')::oid
        FROM public.sentinel_operational_ddl_epoch e CROSS JOIN pg_event_trigger t
        JOIN pg_proc p ON p.oid=t.evtfoid CROSS JOIN pg_control_system() s
        WHERE e.id=1 AND t.evtname='sentinel_operational_evidence_ddl_changed'
          AND t.evtenabled='O' AND t.evtevent='ddl_command_end'
          AND t.evttags IS NULL AND p.oid=to_regprocedure('public.sentinel_operational_evidence_ddl_changed()')
        """).fetchone()
    if guard is None:
        return None
    module = importlib.import_module(module_name)
    tables = sorted(module.extension_tables)
    pairs = sorted(module.extension_triggers)
    # DROP and modifications of the audit itself can escape ddl_command_end.
    # Read native versions of the same public objects the pinned comparison
    # covers, including added columns, defaults, indexes or trigger overloads.
    versions = conn.execute("""
        SELECT kind,id,version FROM (
          WITH sources AS MATERIALIZED (
            SELECT c.oid,c.relname,c.xmin::text AS version,c.ctid::text AS loc
            FROM pg_class c WHERE c.relnamespace='public'::regnamespace
              AND c.relname=ANY(%s::name[])
          ), owned AS MATERIALIZED (
            SELECT oid FROM sources WHERE relname=ANY(%s::name[])
          )
          SELECT 'relation' AS kind,oid::text AS id,version||'/'||loc AS version FROM sources
          UNION ALL SELECT 'column',a.attrelid::text||'/'||a.attnum,a.xmin::text||'/'||a.ctid::text||
                '/'||ty.xmin::text||'/'||ty.ctid::text
            FROM pg_attribute a JOIN owned ON a.attrelid=owned.oid LEFT JOIN pg_type ty ON ty.oid=a.atttypid
            WHERE a.attnum>0 AND NOT a.attisdropped
          UNION ALL SELECT 'default',d.oid::text,d.xmin::text||'/'||d.ctid::text
            FROM pg_attrdef d JOIN owned ON d.adrelid=owned.oid
          UNION ALL SELECT 'constraint',k.oid::text,k.xmin::text||'/'||k.ctid::text
            FROM pg_constraint k JOIN owned ON k.conrelid=owned.oid
          UNION ALL SELECT 'index',i.indexrelid::text,i.xmin::text||'/'||i.ctid::text||'/'||
                c.xmin::text||'/'||c.ctid::text||'/'||am.xmin::text||'/'||am.ctid::text
            FROM pg_index i JOIN owned ON i.indrelid=owned.oid JOIN pg_class c ON c.oid=i.indexrelid
            JOIN pg_am am ON am.oid=c.relam
          UNION ALL SELECT 'trigger',t.oid::text,t.xmin::text||'/'||t.ctid::text
            FROM pg_trigger t JOIN sources s ON t.tgrelid=s.oid
            WHERE NOT t.tgisinternal AND (s.oid IN (SELECT oid FROM owned) OR t.tgname=ANY(%s::name[]))
          UNION ALL SELECT 'function',p.oid::text,p.xmin::text||'/'||p.ctid::text||
                '/'||l.xmin::text||'/'||l.ctid::text||'/'||ty.xmin::text||'/'||ty.ctid::text
            FROM pg_proc p JOIN pg_language l ON l.oid=p.prolang JOIN pg_type ty ON ty.oid=p.prorettype
            WHERE p.pronamespace='public'::regnamespace AND p.proname=ANY(%s::name[])
        ) AS objects ORDER BY kind,id
        """, (sorted(set(tables) | {table for table, _ in pairs}), tables,
              [name for _, name in pairs], sorted(module.extension_functions))).fetchall()
    return (os.getpid(),conn.info.host,conn.info.port,meta,guard,versions,
            hashlib.sha256(catalog.CATALOG_PATH.read_bytes()).hexdigest(),catalog.CATALOG_SHA256)


def require(conn, module_name, *, allow_absent=False):
    if allow_absent or module_name not in _COMPONENTS or not isinstance(conn, psycopg.Connection):
        return catalog.require_extension(conn, module_name, allow_absent=allow_absent)
    started, wall_start = time.monotonic(), time.time()
    identity = _identity(conn, module_name)
    if identity is not None:
        with _LOCK:
            previous = _verified.get(module_name)
        if previous and previous.identity == identity and previous.current():
            return True
    result = catalog.require_extension(conn, module_name)
    proof = Proof(started, wall_start, identity)
    if identity is not None and proof.current():
        with _LOCK:
            _verified[module_name] = proof
    return result
