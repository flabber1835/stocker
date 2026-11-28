"""A short-lived, read-only control history proof for health pollers."""
from __future__ import annotations

from dataclasses import dataclass
from time import monotonic

import psycopg

from sentinel.automation import control_integrity, store
from sentinel.automation.model import AutomationControl, ControlBinding


@dataclass(frozen=True)
class _Proof:
    key: tuple
    history: tuple[int, bool, bool, ControlBinding | None]
    expires: float


_proof: _Proof | None = None
_MAX_EVENTS = 1024


def _witness(conn) -> tuple | None:
    """Small tuples only. All source reads use the enclosing snapshot."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT s.system_identifier::text, pg_postmaster_start_time(), d.oid,
                   current_database(), current_user, current_schemas(true),
                   floor(pg_snapshot_xmax(pg_current_snapshot())::text::numeric / 4294967296),
                   r.oid, r.xmin::text, pg_relation_filenode(r.oid),
                   ARRAY(SELECT concat_ws('/', a.attnum, a.xmin, a.attname, a.atttypid)
                         FROM pg_attribute a WHERE a.attrelid=r.oid AND a.attnum>0
                         ORDER BY a.attnum),
                   ARRAY(SELECT concat_ws('/', e.seq, e.tableoid, e.xmin, e.ctid)
                         FROM sentinel_automation_events e ORDER BY e.seq LIMIT %s)
            FROM pg_control_system() s
            JOIN pg_database d ON d.datname=current_database()
            JOIN pg_class r ON r.oid='sentinel_automation_events'::regclass
            WHERE r.relkind='r' AND NOT r.relrowsecurity AND NOT pg_is_in_recovery()
              AND current_setting('session_replication_role')='origin'
              AND pg_current_xact_id_if_assigned() IS NULL
            """, (_MAX_EVENTS + 1,))
        row = cur.fetchone()
    return row if row is not None and len(row[-1]) <= _MAX_EVENTS else None


def read(conn) -> AutomationControl:
    """The health caller has just ended its table-presence transaction."""
    global _proof
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        control = store._load_control_row(conn)
        try:
            with conn.transaction():
                key = _witness(conn)
        except (psycopg.errors.InsufficientPrivilege, psycopg.errors.UndefinedColumn,
                psycopg.errors.UndefinedFunction, psycopg.errors.WrongObjectType):
            # A restricted role or a source without physical identities can still replay.
            key = None
        prior = _proof
        now = monotonic()
        if key is not None and prior is not None and now < prior.expires and key == prior.key:
            return control_integrity.compare_control(control, prior.history)
        history = control_integrity._replay(conn)
        validated = control_integrity.compare_control(control, history)
        if key is not None:
            _proof = _Proof(key, history, now + 60)
        return validated
