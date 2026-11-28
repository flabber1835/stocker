"""Private PostgreSQL qualification of exact historical mark coordinates."""
from datetime import date, timedelta
from uuid import UUID

import psycopg

from sentinel.core.rolling_reader import RollingPriceReader
from sentinel.feed import normalized_layout as layout, read_contract
from tests.sentinel.test_rolling_snapshot_publisher import pg  # noqa: F401


def _layout(conn, days, securities):
    conn.execute("""CREATE TEMP TABLE sentinel_snapshot_bars(
        candidate_id uuid, security_id text, session date, ticker text, close_signal float8,
        close_unadjusted float8, open_unadjusted float8, volume float8, split_ratio float8,
        dividend_per_share float8, PRIMARY KEY(candidate_id, security_id, session))""")
    conn.execute("""CREATE TEMP TABLE sentinel_normalized_blocks(
        block_sha256 text PRIMARY KEY, canonical_payload text)""")
    conn.execute("""CREATE TEMP TABLE sentinel_candidate_blocks(
        candidate_id uuid, kind text, session date, block_sha256 text,
        PRIMARY KEY(candidate_id, kind, session))""")
    conn.execute(read_contract._BAR_VIEW.replace('CREATE OR REPLACE VIEW', 'CREATE TEMP VIEW'))
    conn.execute("""INSERT INTO sentinel_normalized_blocks
        SELECT day::text, (SELECT jsonb_build_object('rows', jsonb_agg(jsonb_build_object(
            'security_id', i::text, 'ticker', 'T'||i, 'close_signal', day*2+i,
            'close_unadjusted', day+i, 'open_unadjusted', day+i+1,
            'volume', 100000*i::bigint, 'split_ratio', 1.0, 'dividend_per_share', 0.0)))::text
            FROM generate_series(1,%s) AS i)
        FROM generate_series(1,%s) AS day""", (securities, days))
    candidate = UUID(int=1)
    conn.execute("""INSERT INTO sentinel_candidate_blocks
        SELECT %s,'BARS',date '2025-01-01'+day,day::text FROM generate_series(1,%s) day""",
        (candidate, days))
    for table in ('sentinel_snapshot_bars', 'sentinel_normalized_blocks', 'sentinel_candidate_blocks'):
        conn.execute('ANALYZE '+table)
    return candidate


def _expansions(node):
    return ((node['Actual Loops'] if node.get('Function Name') == 'jsonb_to_recordset' else 0)
        + sum(_expansions(child) for child in node.get('Plans', [])))


def compare(conn, *, days, securities, coordinates=None):
    candidate = _layout(conn, days, securities)
    start = date(2025, 1, 1)
    if coordinates is None:
        coordinates = [(1, 2), (2, 2), (3, days//2), (4, days), (securities+1, 2)]
    params = ([str(i) for i, _ in coordinates], [start+timedelta(days=d) for _, d in coordinates],
        candidate)
    # The router must recognize the SQL used by the real economic reader.
    original = next(query for query in RollingPriceReader.prices.__code__.co_consts
                    if isinstance(query, str) and 'FROM unnest(' in query)
    assert original == layout._ANCHOR_POINTS
    direct = read_contract.route(original, shared=True)
    result = {}
    for name, sql in [('logical', direct), ('routed', layout.query_router(conn)(original))]:
        rows = sorted(conn.execute(sql, params).fetchall())
        assert rows == sorted((str(i), start+timedelta(days=d), 'T'+str(i), d+i, d*2+i)
                             for i, d in coordinates if i <= securities)
        explain = conn.execute('EXPLAIN (ANALYZE, VERBOSE, BUFFERS, FORMAT JSON) '+sql,
            params).fetchone()[0][0]
        plan = explain['Plan']
        result[name] = dict(rows=len(rows), expanded_blocks=_expansions(plan),
            temp_written_blocks=plan['Temp Written Blocks'], elapsed_ms=explain['Execution Time'])
    return result


def test_packed_anchor_prices_expand_only_requested_sessions(pg, monkeypatch):
    monkeypatch.setattr(layout, 'available', lambda conn: True)
    with psycopg.connect(pg.sync_dsn) as conn:
        result = compare(conn, days=45, securities=100)
    assert result['routed']['expanded_blocks'] == 3
    assert result['routed']['temp_written_blocks'] == 0
    monkeypatch.setattr(layout, 'available', lambda conn: False)
    assert layout.query_router(None)(layout._ANCHOR_POINTS) == layout._ANCHOR_POINTS
