"""Explicit presentation DDL handoff; runtime evidence readers remain strict."""
from __future__ import annotations

from sentinel import operational_ddl_handoff
from sentinel.panel import review_schema

DOMAINS = operational_ddl_handoff.DOMAINS
# Real PostgreSQL ddl_command_end records: two public tables and one function.
# Trigger-creation records have no schema_name and do not advance this witness.
DDL_ADVANCE = 3


class ReviewMigrationRefused(RuntimeError):
    pass


def install(conn):
    """Caller owns migration, financial-writer locks, fence and transaction.

    Only a genuinely absent extension enters this transfer. An existing schema
    never repairs an old prefix, including one invalidated by the first PR564.
    """
    if review_schema.require_schema(conn, allow_absent=True):
        return
    with operational_ddl_handoff.transfer(conn, expected_advance=DDL_ADVANCE,
            label='presentation migration', refusal=ReviewMigrationRefused):
        review_schema.install(conn)
        review_schema.require_schema(conn)
