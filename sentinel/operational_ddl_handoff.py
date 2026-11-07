"""Migration-only signed coverage transfer across an exact additive DDL step."""
from __future__ import annotations

from contextlib import contextmanager

from psycopg import sql

from sentinel import operational_ddl_epoch
from sentinel.execution import evidence_projection as coverage, evidence_schema

DOMAINS = ('OBSERVATION', 'MIRROR')


def _require(value, reason, refusal):
    if not value:
        raise refusal(reason)


@contextmanager
def transfer(conn, *, expected_advance: int, label: str, refusal: type[Exception]):
    """Caller owns migration/writer exclusion, transaction and exact DDL check.

    Authenticate each original prefix before yielding. Rebind only its inventory
    after the exact epoch transition; preserve absent and pending coverage. An
    existing stale receipt cannot enter this operation as a repair opportunity.
    """
    if (type(expected_advance) is not int or expected_advance < 1
            or not isinstance(label, str) or not label or len(label) > 100
            or not isinstance(refusal, type) or not issubclass(refusal, Exception)):
        raise ValueError('invalid operational DDL handoff contract')
    if not evidence_schema.require_schema(conn, allow_absent=True):
        yield
        return
    # Include heads/coverage/source tables and the DDL epoch relation. The latter
    # also blocks unrelated DDL's event-trigger write until this owner finishes.
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
    yield
    _require(operational_ddl_epoch.current(conn) == (epoch[0], epoch[1] + expected_advance),
             label+' DDL advance differs', refusal)
    for domain, (coordinates, payload, material) in before.items():
        _require(coverage.head(conn, domain, lock=True) == coordinates,
                 label+' evidence head changed', refusal)
        _require(coverage._authenticated(conn, domain) == payload,
                 label+' authenticated prefix changed', refusal)
        after = coverage._inventory_material(conn, domain)
        after[-1] = material[-1]
        _require(after == material, label+' source inventory changed', refusal)
        if payload is None:
            continue
        rebound = coverage.write(conn, domain, through=payload['through'], body=payload['body'])
        _require({k: v for k, v in rebound.items() if k != 'inventory'} ==
                 {k: v for k, v in payload.items() if k != 'inventory'},
                 label+' changed prefix content', refusal)
