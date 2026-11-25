"""The Alpaca sealing key table supplies bytewise order from its primary key."""
from __future__ import annotations

import ast
import inspect
import json
import textwrap

from sentinel.feed import rolling_builder, rolling_store
from sentinel.feed.rolling_contract import PriceWindow, RestartRequirement
from tests.sentinel.test_rolling_snapshot_publisher import conn, pg

__all__ = ["conn", "pg"]


ORDERED_KEYS = (
    'SELECT session,security_id FROM alpaca_expected_keys '
    'ORDER BY session,security_id COLLATE "C"'
)


def _nodes(plan):
    yield plan
    for child in plan.get("Plans", ()):
        yield from _nodes(child)


def _plan(conn):
    raw = conn.execute("EXPLAIN (FORMAT JSON) " + ORDERED_KEYS).fetchone()[0]
    value = json.loads(raw) if isinstance(raw, str) else raw
    return list(_nodes(value[0]["Plan"]))


def _candidate(conn, window, securities, evidence):
    candidate = rolling_store.begin(
        conn, window=window, reference_sha256=evidence,
        source_evidence_sha256=evidence, expected_publication_version=None,
        dependencies_sha256=rolling_store.digest({}))
    rolling_store.write_bars(conn, candidate, (
        {"session": day, "security_id": security, "ticker": "AAA",
         "close_signal": 50.0, "close_unadjusted": 50.0,
         "open_unadjusted": 49.0, "volume": 100000.0,
         "split_ratio": 1.0, "dividend_per_share": 0.0}
        for day in window.sessions for security in securities))
    rolling_store.write_benchmarks(conn, candidate, (
        {"session": day, "spy_total_return": 600.0,
         "bil_open_signal": 91.0, "bil_close_signal": 91.0,
         "bil_close_adjusted": 100.0, "bil_close_unadjusted": 91.0}
        for day in window.sessions))
    return candidate


def _seal_from_keys(conn, window, securities, evidence, ddl):
    candidate = _candidate(conn, window, securities, evidence)
    conn.execute(ddl)
    with conn.cursor() as cur:
        with cur.copy("COPY alpaca_expected_keys(session,security_id) FROM STDIN") as copy:
            for day in window.sessions:
                for security in securities:
                    copy.write_row((day, security))
    conn.execute("ANALYZE alpaca_expected_keys")
    plan = _plan(conn)
    rows = [(str(day), security) for day, security in conn.execute(ORDERED_KEYS)]
    manifest = rolling_store.seal(
        conn, candidate, expected_keys=rows,
        normalization_version=rolling_builder.ALPACA_NORMALIZATION,
        requirements=RestartRequirement(), provider="ALPACA_OPENFIGI")
    conn.commit()  # Drop the test-only table before comparing the other DDL.
    return rows, plan, manifest


def test_expected_key_index_order_avoids_sort_without_changing_manifest(conn):
    source = ast.parse(textwrap.dedent(inspect.getsource(rolling_builder.build_alpaca)))
    uses = [node for node in ast.walk(source)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr == "execute" and node.args
            and isinstance(node.args[0], ast.Name)
            and node.args[0].id == "ALPACA_EXPECTED_KEYS_DDL"]
    assert len(uses) == 1
    assert conn.execute("SELECT datcollate FROM pg_database "
                        "WHERE datname=current_database()").fetchone()[0] != "C"
    ddl = rolling_builder.ALPACA_EXPECTED_KEYS_DDL
    assert ddl.count(' COLLATE "C"') == 1
    old_ddl = ddl.replace(' COLLATE "C"', "")
    window = PriceWindow.through("2026-09-14")
    securities = sorted(["A", "Z", "a", "é", *[f"S{n:03}" for n in range(96)]],
                        key=lambda value: value.encode("utf-8"))
    evidence = rolling_store.put_evidence(conn, {"fixture": "Alpaca C order"})
    expected = [(str(day), security) for day in window.sessions
                for security in securities]

    new_rows, new_plan, new_manifest = _seal_from_keys(
        conn, window, securities, evidence, ddl)
    assert new_rows == expected
    assert any(node.get("Index Name") == "alpaca_expected_keys_pkey"
               for node in new_plan), new_plan
    assert not any("Sort" in node["Node Type"] for node in new_plan), new_plan

    old_rows, old_plan, old_manifest = _seal_from_keys(
        conn, window, securities, evidence, old_ddl)
    assert old_rows == expected
    assert any("Sort" in node["Node Type"] for node in old_plan), old_plan
    assert new_manifest == old_manifest
