"""Regression coverage for issue #168: unchanged overlap bars are true no-ops."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "shared"))

from tests.support.postgres import _EphemeralPostgres  # noqa: E402

from sentinel.feed import store as S  # noqa: E402
from stock_strategy_shared.wealth_core.feed import VendorBar  # noqa: E402


RUN_1 = "00000000-0000-0000-0000-000000000001"
RUN_2 = "00000000-0000-0000-0000-000000000002"
RUN_3 = "00000000-0000-0000-0000-000000000003"


@pytest.fixture(scope="module")
def pg():
    try:
        server = _EphemeralPostgres()
        server.start()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"ephemeral Postgres unavailable: {exc}")
    try:
        yield server
    finally:
        server.stop()


@pytest.fixture()
def conn(pg):
    c = S.connect(pg.sync_dsn)
    with c.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS sentinel_bars")
        cur.execute(
            "CREATE TABLE sentinel_bars ("
            " security_id TEXT NOT NULL, session DATE NOT NULL, ticker TEXT NOT NULL,"
            " close_signal DOUBLE PRECISION, close_unadjusted DOUBLE PRECISION NOT NULL,"
            " open_unadjusted DOUBLE PRECISION, volume DOUBLE PRECISION,"
            " split_ratio DOUBLE PRECISION NOT NULL DEFAULT 1.0,"
            " dividend_per_share DOUBLE PRECISION NOT NULL DEFAULT 0.0,"
            " last_written_run_id UUID, PRIMARY KEY (security_id, session))")
    c.commit()
    try:
        yield c
    finally:
        c.close()


def bar(session="2026-08-14", *, close=100.0, open_=99.0, volume=1_000_000,
        split_ratio=1.0, dividend=0.0):
    return VendorBar(
        session=session,
        security_id="SEC1",
        ticker="AAA",
        raw_close=close,
        raw_open=open_,
        volume=volume,
        split_ratio=split_ratio,
        dividend_per_share=dividend,
    )


def state(conn, session="2026-08-14"):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT xmin::text, close_signal, close_unadjusted, split_ratio,"
            " last_written_run_id::text FROM sentinel_bars"
            " WHERE security_id='SEC1' AND session=%s",
            (session,),
        )
        return cur.fetchone()


def test_identical_overlap_is_no_physical_update_and_keeps_provenance(conn):
    original = bar()
    assert S.write_bars(conn, [original], run_id=RUN_1) == 1
    before = state(conn)

    # Bare VendorBar carries close_signal=None.  Replaying that NULL is part of
    # the contract: ordinary <> comparisons would not be NULL-safe here.
    assert S.write_bars(conn, [original], run_id=RUN_2) == 1
    after = state(conn)

    assert after == before
    assert after[4] == RUN_1


def test_real_content_change_updates_tuple_and_current_provenance(conn):
    S.write_bars(conn, [bar()], run_id=RUN_1)
    before = state(conn)

    S.write_bars(conn, [bar(close=101.5)], run_id=RUN_2)
    after = state(conn)

    assert after[0] != before[0], "xmin must change when PostgreSQL physically updates"
    assert after[2] == 101.5
    assert after[4] == RUN_2


def test_null_to_value_is_a_real_change(conn):
    S.write_bars(conn, [bar()], run_id=RUN_1)
    before = state(conn)

    normalised = SimpleNamespace(vendor=bar(), close_signal=98.25)
    S.write_bars(conn, [normalised], run_id=RUN_2)
    after = state(conn)

    assert before[1] is None
    assert after[1] == 98.25
    assert after[0] != before[0]
    assert after[4] == RUN_2


def test_new_session_still_inserts_normally(conn):
    S.write_bars(conn, [bar("2026-08-14")], run_id=RUN_1)
    S.write_bars(conn, [bar("2026-08-17")], run_id=RUN_2)

    with conn.cursor() as cur:
        cur.execute("SELECT session::text, last_written_run_id::text"
                    " FROM sentinel_bars ORDER BY session")
        assert cur.fetchall() == [
            ("2026-08-14", RUN_1),
            ("2026-08-17", RUN_2),
        ]


def test_split_non_downgrade_remains_noop_unless_other_content_changes(conn):
    S.write_bars(conn, [bar(split_ratio=2.0)], run_id=RUN_1)
    before = state(conn)

    # Incoming 1.0 is absence of split evidence, so effective durable content is
    # unchanged: no tuple rewrite and no provenance reassignment.
    S.write_bars(conn, [bar(split_ratio=1.0)], run_id=RUN_2)
    after_noop = state(conn)
    assert after_noop == before
    assert after_noop[3] == 2.0

    # A real price restatement must still update, while retaining the proven
    # split ratio under the existing non-downgrade rule.
    S.write_bars(conn, [bar(close=101.0, split_ratio=1.0)], run_id=RUN_3)
    after_change = state(conn)
    assert after_change[0] != before[0]
    assert after_change[2] == 101.0
    assert after_change[3] == 2.0
    assert after_change[4] == RUN_3
