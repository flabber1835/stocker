"""Explicit presentation DDL handoff; runtime evidence readers remain strict."""
from __future__ import annotations

from psycopg import sql

from sentinel.execution import evidence_projection as coverage, evidence_schema
from sentinel import operational_ddl_epoch
from sentinel.panel import review_schema

DOMAINS = ('OBSERVATION', 'MIRROR')
# Real PostgreSQL ddl_command_end records: two public tables and one function.
# Trigger-creation records have no schema_name and do not advance this witness.
DDL_ADVANCE = 3


class ReviewMigrationRefused(RuntimeError):
    pass


def require(value, reason):
    if not value:
        raise ReviewMigrationRefused(reason)


def install(conn):
    """Caller owns migration, financial-writer locks, fence and transaction.

    Only a genuinely absent extension enters this transfer. An existing schema
    never repairs an old prefix, including one invalidated by the first PR564.
    """
    if review_schema.require_schema(conn, allow_absent=True):
        return
    if not evidence_schema.require_schema(conn, allow_absent=True):
        review_schema.install(conn)
        return
    # Relation locks also exclude DDL and source publishers that do not use the
    # financial advisory owner. Re-read all material after acquiring the locks.
    names = {row[0] for domain in DOMAINS
             for row in coverage._inventory_material(conn, domain)[2]}
    conn.execute(sql.SQL('LOCK TABLE {} IN SHARE MODE').format(
        sql.SQL(',').join(sql.Identifier(name) for name in sorted(names))))
    before = {}
    for domain in DOMAINS:
        coordinates = coverage.head(conn, domain, lock=True)
        payload = coverage.load(conn, domain)
        before[domain] = (coordinates, payload, coverage._inventory_material(conn, domain))
    epoch = operational_ddl_epoch.current(conn)
    review_schema.install(conn)
    review_schema.require_schema(conn)
    require(operational_ddl_epoch.current(conn) == (epoch[0], epoch[1] + DDL_ADVANCE),
            'presentation migration DDL advance differs')
    for domain, (coordinates, payload, material) in before.items():
        require(coverage.head(conn, domain, lock=True) == coordinates,
                'presentation migration evidence head changed')
        require(coverage._authenticated(conn, domain) == payload,
                'presentation migration authenticated prefix changed')
        after = coverage._inventory_material(conn, domain)
        after[-1] = material[-1]
        require(after == material, 'presentation migration source inventory changed')
        if payload is None:
            continue
        rebound = coverage.write(conn, domain, through=payload['through'], body=payload['body'])
        require({k: v for k, v in rebound.items() if k != 'inventory'} ==
                {k: v for k, v in payload.items() if k != 'inventory'},
                'presentation migration changed prefix content')
