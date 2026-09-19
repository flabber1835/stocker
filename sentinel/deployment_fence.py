"""Read-only global migration fence, including the genuinely empty bootstrap."""
from sentinel import schema


class DeploymentFenceRefused(RuntimeError):
    pass


def require(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                    "WHERE n.nspname='public' AND c.relname LIKE 'sentinel\\_%' ESCAPE '\\' "
                    "AND c.relkind IN ('r','p','v','m','f')")
        names = {row[0] for row in cur.fetchall()}
        behavioral = names - schema._FEED_TABLES - {schema._BACKUP_INFRASTRUCTURE_TABLE}
        if not behavioral:
            return {'status': 'EMPTY_BEHAVIORAL_SCHEMA'}
        if not {'sentinel_automation_control', 'sentinel_automation_lease'} <= behavioral:
            raise DeploymentFenceRefused('partial behavioral state has no global automation fence')
        cur.execute('SELECT kill_switch_engaged,generation FROM sentinel_automation_control WHERE id=1')
        control = cur.fetchone()
        cur.execute('SELECT holder_id,control_generation,expires_at FROM sentinel_automation_lease WHERE id=1')
        lease = cur.fetchone()
        if control is None or control[0] is not True or lease is None or lease != (None, None, None):
            raise DeploymentFenceRefused('durable kill and invalidated lease are required before migration')
        return {'status': 'DURABLY_FENCED', 'generation': int(control[1])}
