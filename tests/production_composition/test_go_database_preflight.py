"""Fast PostgreSQL reproductions of the actual GO read boundaries."""
import ast
import datetime as dt

import pytest

from scripts import sentinel_go_validate as go
from sentinel import schema
from sentinel.feed import maintenance, readiness, recent_reconciliation, store
from tests.support.postgres import _EphemeralPostgres


@pytest.fixture(scope="module")
def conn():
    server = _EphemeralPostgres()
    server.start()  # Required capability: never turn this gate into a skip.
    connection = store.connect(server.sync_dsn)
    try:
        schema.ensure_schema(connection)
        store.migrate_schema(connection)
        yield connection
    finally:
        connection.close()
        server.stop()


@pytest.mark.parametrize("table_installed", [False, True])
@pytest.mark.parametrize("loader", [
    maintenance.load_sep_cursor, maintenance.load_actions_cursor,
    recent_reconciliation.load_cursor,
])
def test_real_cursor_loader_is_read_only(conn, loader, table_installed):
    conn.rollback()
    if not table_installed:
        with conn.cursor() as cur:
            cur.execute("ALTER TABLE sentinel_processed_sessions"
                        " RENAME TO preflight_saved_cursors")
        conn.commit()
    with conn.cursor() as cur:
        cur.execute("BEGIN TRANSACTION READ ONLY")
    try:
        assert loader(conn) is None
        result = readiness._impl.Readiness()
        readiness._add_source_maintenance_checks(
            conn, result, today="2026-08-18", required_through="2026-08-18")
        assert len(result.checks) == 3
        assert all(check.status == readiness.FAIL for check in result.checks)
        assert not result.ready
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            assert cur.fetchone() == (1,)
            cur.execute("SELECT to_regclass('sentinel_processed_sessions')")
            assert (cur.fetchone()[0] is not None) == table_installed
    finally:
        conn.rollback()
        if not table_installed:
            with conn.cursor() as cur:
                cur.execute("ALTER TABLE preflight_saved_cursors"
                            " RENAME TO sentinel_processed_sessions")
            conn.commit()


def _nodes(node):
    yield node
    for child in node.get("Plans", ()):
        yield from _nodes(child)


def _bad_shape(plan):
    # Execute the production predicate, so a regression in GO itself fails.
    tree = ast.parse(go._DATABASE_HEALTH_CODE)
    assignment = next(node for node in ast.walk(tree)
                      if isinstance(node, ast.Assign)
                      and any(isinstance(t, ast.Name)
                              and t.id == "predecessor_bad_shape"
                              for t in node.targets))
    scope = {"nodes": _nodes, "predecessor_plan": list(_nodes(plan))}
    exec(compile(ast.Module(body=[assignment], type_ignores=[]),
                 "GO plan predicate", "exec"), scope)
    return scope["predecessor_bad_shape"]


def _bounded_lookup(plan):
    tree = ast.parse(go._DATABASE_HEALTH_CODE)
    function = next(node for node in tree.body
                    if isinstance(node, ast.FunctionDef)
                    and node.name == 'bounded_predecessor_lookup')
    scope = {}
    exec(compile(ast.Module(body=[function], type_ignores=[]),
                 'GO bounded lookup', 'exec'), scope)
    return scope['bounded_predecessor_lookup'](list(_nodes(plan)))


@pytest.mark.parametrize('index,direction', [
    ('idx_sentinel_bars_predecessor', 'Forward'),
    ('sentinel_bars_pkey', 'Backward'),
])
def test_bounded_lookup_requires_order_bounds_and_limit(index, direction):
    scan = {'Node Type': 'Index Scan', 'Relation Name': 'sentinel_bars',
            'Index Name': index, 'Scan Direction': direction,
            'Index Cond': "((security_id = ids.security_id) AND (session < '2026-08-17'::date))"}
    plan = {'Node Type': 'Limit', 'Plan Rows': 1, 'Plans': [scan]}
    assert _bounded_lookup(plan)
    assert not _bounded_lookup(scan)
    for field, value in [('Scan Direction', 'invalid'),
                         ('Index Cond', '(security_id = ids.security_id)'),
                         ('Index Cond', "(session < '2026-08-17'::date)"),
                         ('Node Type', 'Seq Scan'),
                         ('Index Name', 'unrecognized')]:
        assert not _bounded_lookup({**plan, 'Plans': [{**scan, field: value}]})
    assert not _bounded_lookup({**plan, 'Plan Rows': 1000})


def test_plan_guard_distinguishes_metadata_and_price_history_sorts():
    metadata = {"Node Type": "Sort", "Plans": [
        {"Node Type": "Seq Scan", "Relation Name": "sentinel_corpus_publications"}]}
    assert not _bad_shape(metadata)
    for kind in ("Sort", "Gather Merge"):
        assert _bad_shape({"Node Type": kind, "Plans": [
            {"Node Type": "Index Scan", "Relation Name": "sentinel_bars"}]})


def test_real_predecessor_plan_with_publication_metadata(conn):
    cutoff = dt.date(2026, 8, 17)
    with conn.cursor() as cur:
        cur.execute("INSERT INTO sentinel_bars"
                    " (security_id,session,ticker,close_signal,close_unadjusted,"
                    " last_written_run_id)"
                    " SELECT 'SEC' || s, %s::date - d, 'SEC' || s, 10, 11,"
                    " '00000000-0000-0000-0000-000000000001'::uuid"
                    " FROM generate_series(1,4000) s"
                    " CROSS JOIN generate_series(1,270) d", (cutoff,))
        cur.execute("INSERT INTO sentinel_corpus_publications"
                    " (window_start,window_end,evidence,run_id)"
                    " SELECT %s,%s,'{}'::jsonb,"
                    " ('00000000-0000-0000-0000-' || lpad(n::text,12,'0'))::uuid"
                    " FROM generate_series(1,4) n",
                    (cutoff - dt.timedelta(days=270), cutoff))
        cur.execute("ANALYZE sentinel_bars")
        cur.execute("ANALYZE sentinel_corpus_publications")
        cur.execute("EXPLAIN (FORMAT JSON) " + store._PREVIOUS_OBSERVATIONS_SQL,
                    (cutoff,))
        plan = cur.fetchone()[0][0]["Plan"]
    conn.rollback()
    nodes = list(_nodes(plan))
    assert not _bad_shape(plan), plan
    assert _bounded_lookup(plan), plan
    assert not any(n.get("Relation Name") == "sentinel_bars"
                   and n["Node Type"] in {"Seq Scan", "Parallel Seq Scan"}
                   for n in nodes), plan
