"""Docker health check for alert delivery, independent of the webhook path."""
from __future__ import annotations

import os
import sys

if __name__ == '__main__' and len(sys.argv) == 1:
    from sentinel.supervisor_health import probe

    raise SystemExit(probe('/tmp/sentinel-alert-health.sock'))

from sentinel import alert_health, schema
from sentinel.config import SentinelConfig
from sentinel.feed import store as feed_store


class AlertSchemaCheck:
    """One warm reader. Revalidate on changes to either source of delivery health."""

    def __init__(self):
        self.verified = None

    def __call__(self, conn):
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        metadata = conn.execute("""
            SELECT system_identifier,current_database(),pg_postmaster_start_time(),current_user,
                   current_schemas(true),floor(pg_snapshot_xmax(pg_current_snapshot())::text::numeric/4294967296),
                   to_regclass('public.sentinel_operational_ddl_epoch')::oid
            FROM pg_control_system()""").fetchone()
        epoch = (conn.execute("SELECT incarnation,epoch,tableoid,xmin::text,ctid::text "
                     "FROM public.sentinel_operational_ddl_epoch WHERE id=1").fetchone()
                 if metadata[-1] else None)
        # DROP and changes to the event trigger itself need an independent
        # witness. Read metadata for just the two tables supplying this probe.
        sources = conn.execute("""
            WITH src AS MATERIALIZED (
              SELECT c.oid,c.xmin::text AS version FROM pg_class c
              WHERE c.oid IN (to_regclass('public.sentinel_alert_dispatcher_health'),
                              to_regclass('public.sentinel_alert_outbox')))
            SELECT 'relation',oid::text,version FROM src
            UNION ALL SELECT 'column',a.attrelid::text||'/'||a.attnum,a.xmin::text
                FROM pg_attribute a JOIN src ON a.attrelid=src.oid
            UNION ALL SELECT 'constraint',c.oid::text,c.xmin::text
                FROM pg_constraint c JOIN src ON c.conrelid=src.oid
            UNION ALL SELECT 'trigger',t.oid::text,t.xmin::text
                FROM pg_trigger t JOIN src ON t.tgrelid=src.oid
            UNION ALL SELECT 'index',i.indexrelid::text,i.xmin::text
                FROM pg_index i JOIN src ON i.indrelid=src.oid
            UNION ALL SELECT 'default',d.oid::text,d.xmin::text
                FROM pg_attrdef d JOIN src ON d.adrelid=src.oid
            ORDER BY 1,2""").fetchall()
        guard = conn.execute("""
            SELECT e.oid,e.xmin::text,p.oid,p.xmin::text FROM pg_event_trigger e
            JOIN pg_proc p ON p.oid=e.evtfoid
            WHERE e.evtname='sentinel_operational_evidence_ddl_changed'
              AND e.evtenabled IN ('O','A') AND current_setting('session_replication_role')='origin'
            """).fetchone()
        token = (metadata, epoch, guard, sources)
        if epoch is None or guard is None or token != self.verified:
            schema.require_runtime_schema(conn)
            self.verified = token


def observe(*, schema_check=None) -> tuple[int, dict]:
    config = SentinelConfig.from_env()
    if not config.database_url:
        return 1, {'healthy': False, 'reason': 'database URL is unset'}
    dispatcher_id = os.environ.get(
        "SENTINEL_AUTOMATION_ALERT_DISPATCHER_ID", "primary").strip()
    try:
        maximum_age, startup_grace = alert_health.health_intervals_from_env()
    except ValueError as exc:
        return 1, {'healthy': False, 'reason': str(exc)}

    conn = None
    try:
        conn = feed_store.connect(config.database_url, connect_timeout=2, statement_timeout_ms=2000)
        conn.read_only = True
        (schema_check or schema.require_runtime_schema)(conn)
        health = alert_health.require_healthy(
            conn, dispatcher_id=dispatcher_id,
            maximum_age_seconds=maximum_age,
            startup_grace_seconds=startup_grace)
    except Exception as exc:                                  # noqa: BLE001
        return 1, {'healthy': False, 'reason': f'{type(exc).__name__}: {exc}'}
    finally:
        if conn is not None:
            conn.close()
    return 0, {'healthy': True, 'dispatcher': health.dispatcher_id, 'state': health.state}


def main() -> int:
    status, payload = observe()
    if status:
        print('ALERT_DISPATCHER_UNHEALTHY: '+payload['reason'], file=sys.stderr)
    else:
        print('alert_dispatcher_healthy:true '
              f"dispatcher={payload['dispatcher']} state={payload['state']}")
    return status


if __name__ == "__main__":  # pragma: no cover
    if sys.argv[1:] != ['--direct']:
        raise SystemExit('expected --direct or the supervised health probe')
    raise SystemExit(main())
