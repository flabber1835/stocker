"""Reproduce the released 65-event feed installations in private databases."""
import gzip
import json
from pathlib import Path

from sentinel import coverage_recovery_catalog as catalog, schema
from sentinel.execution.evidence_projection import digest


def statements(contract):
    fixture = Path(__file__).with_name('coverage-feed-ddl-v1.json.gz')
    with gzip.open(fixture, 'rt', encoding='utf-8') as stream:
        archive = json.load(stream)
    ddl = archive['original_ddl']
    if contract == catalog.POST_COMPACTION:
        ddl[archive['guard_index']] = archive['successor_delete_guard']
    assert digest([schema._ORDER_AMOUNT_DDL, ddl]) == contract
    return ddl


def install(conn, contract=catalog.ORIGINAL):
    for statement in statements(contract):
        conn.execute(statement)
    conn.commit()


def price_delete_guard(contract):
    return next(statement for statement in statements(contract) if statement.startswith(
        'CREATE OR REPLACE FUNCTION sentinel_acquisition_price_delete_guard('))
