"""Independent PIT authority for disputed cash actions."""
from __future__ import annotations

import copy
from decimal import Decimal

import pytest

from sentinel.feed import corporate_action_authority as CAA
from sentinel.feed import ingest, maintenance, sharadar, store
from sentinel.feed.source_authority.corporate_action_data import (
    CASH_ADJUDICATION_AUTHORITIES,
)
from tests.support.postgres import _EphemeralPostgres

EVENT_DAY = "2026-05-04"
END = "2026-05-08"


def tri_action(value="1.36"):
    return {
        "ticker": "TRI", "date": EVENT_DAY, "action": "dividend",
        "value": value, "contraticker": None,
    }


def test_tri_stale_component_is_replaced_and_other_distribution_remains_additive():
    rows = [
        tri_action("1.36"),
        {"ticker": "TRI", "date": EVENT_DAY,
         "action": "specialdividend", "value": "0.25",
         "contraticker": None},
    ]
    resolved = CAA.resolve_dividends(rows, [EVENT_DAY])
    assert resolved.dividends[("TRI", EVENT_DAY)] == Decimal("1.685518")
    assert len(resolved.adjudications) == 1
    audit = resolved.adjudications[0]
    assert audit.disposition == "APPLIED"
    assert audit.source_amount == "1.36"
    assert audit.final_cash_amount == "1.435518"
    assert audit.source_content_sha256 == \
        "984deaf590f97905becab406a14eb66bce78db8275e66a7f0077202e27401d9d"


def test_source_convergence_is_accepted_without_double_correction():
    resolved = CAA.resolve_dividends([tri_action("1.435518")], [EVENT_DAY])
    assert resolved.dividends[("TRI", EVENT_DAY)] == Decimal("1.435518")
    assert resolved.adjudications[0].disposition == "SOURCE_CONVERGED"


def test_flagged_event_with_no_reviewed_authority_fails_closed():
    with pytest.raises(CAA.CorporateActionAuthorityRefused,
                       match="exactly one reviewed authority"):
        CAA.resolve_dividends([tri_action()], [EVENT_DAY], authorities=())


def test_flagged_event_with_third_unreviewed_amount_fails_closed():
    with pytest.raises(CAA.CorporateActionAuthorityRefused,
                       match="matches neither reviewed stale"):
        CAA.resolve_dividends([tri_action("1.40")], [EVENT_DAY])


def test_late_independent_source_has_no_historical_pit_authority():
    record = copy.deepcopy(CASH_ADJUDICATION_AUTHORITIES[0])
    record["source_published_at"] = "2026-05-04T10:00:00-04:00"
    record["record_sha256"] = CAA.authority_record_sha256(record)
    with pytest.raises(CAA.CorporateActionAuthorityRefused,
                       match="after the 2026-05-04 XNYS open"):
        CAA.validate_authority(record)


def test_retained_source_text_is_bound_by_its_independent_content_hash():
    record = copy.deepcopy(CASH_ADJUDICATION_AUTHORITIES[0])
    record["source_evidence_text"] += "."
    record["record_sha256"] = CAA.authority_record_sha256(record)
    with pytest.raises(CAA.CorporateActionAuthorityRefused,
                       match="source-content SHA-256"):
        CAA.validate_authority(record)


def test_record_hash_binds_the_complete_reviewed_authority():
    record = copy.deepcopy(CASH_ADJUDICATION_AUTHORITIES[0])
    record["final_cash_amount"] = "9.99"
    with pytest.raises(CAA.CorporateActionAuthorityRefused,
                       match="immutable record SHA-256"):
        CAA.validate_authority(record)


def test_v7_semantic_replay_scope_contains_the_tri_event():
    assert CAA.semantic_replay_dates(
        market_start="2026-01-02", market_end="2026-09-11") == [EVENT_DAY]


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
    connection = store.connect(pg.sync_dsn)
    with connection.cursor() as cur:
        for table in (
                "sentinel_anomaly_observation_events",
                "sentinel_corpus_anomalies",
                "sentinel_publication_validation_receipts",
                "sentinel_publication_validation_policy",
                "sentinel_corpus_publications", "sentinel_bars",
                "sentinel_spy_total_return", "sentinel_defensive_bars",
                "sentinel_action_generation_events",
                "sentinel_action_observations", "sentinel_action_generations",
                "sentinel_actions", "sentinel_universe",
                "sentinel_processed_sessions", "feed_ingest_runs",
                "sentinel_ingest_rejections"):
            cur.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
    connection.commit()
    store.require_feed_schema(connection)
    yield connection
    connection.close()


def tri_vendor(*, cash="1.36"):
    from sentinel.feed import calendar

    sessions = calendar.sessions_in_range("2026-04-20", END)
    action = tri_action(cash)

    def fetch(table, params=None, **_kwargs):
        params = dict(params or {})
        lo = str(params.get("date.gte", "0000-00-00"))
        hi = str(params.get("date.lte", "9999-99-99"))
        if table == sharadar.SEP:
            return [
                {"date": day, "ticker": "TRI", "close": 100.0,
                 "closeunadj": 100.0, "open": 99.0, "volume": 1_000_000,
                 "lastupdated": day}
                for day in sessions if lo <= day <= hi
            ]
        if table == sharadar.ACTIONS:
            return [action] if lo <= EVENT_DAY <= hi else []
        if table == sharadar.SFP:
            return []
        if table == sharadar.TICKERS:
            return [{
                "permaticker": "P:TRI", "ticker": "TRI",
                "firstpricedate": "2002-06-12", "lastpricedate": None,
                "relatedtickers": "", "category": "Domestic Common Stock",
            }]
        return []

    return fetch


def _seed(conn, *, cash="1.36"):
    return ingest.seed(
        conn, date_from="2026-04-20", date_to=END,
        fetch=tri_vendor(cash=cash))


def _tri_bar_dividend(conn):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT dividend_per_share FROM sentinel_bars"
            " WHERE ticker='TRI' AND session=%s", (EVENT_DAY,))
        row = cur.fetchone()
    assert row is not None
    return float(row[0])


def test_common_mode_sharadar_fact_loses_authority_but_source_is_preserved(conn):
    # The reproduced case has the same stale 1.36 fact on the Sharadar ACTIONS
    # surface and in Sharadar's total-return economics. Internal vendor agreement
    # therefore cannot grant authority over the independently finalized term.
    sharadar_actions_cash = Decimal("1.36")
    sharadar_sep_implied_cash = Decimal("1.36")
    assert sharadar_actions_cash == sharadar_sep_implied_cash

    _seed(conn)
    assert _tri_bar_dividend(conn) == pytest.approx(1.435518)

    with conn.cursor() as cur:
        cur.execute(
            "SELECT value,source_payload FROM sentinel_active_actions"
            " WHERE ticker='TRI' AND session=%s AND action='dividend'",
            (EVENT_DAY,))
        source = cur.fetchone()
        cur.execute(
            "SELECT evidence FROM sentinel_corpus_publications"
            " WHERE evidence->>'kind'='actions_cash_adjudication_v7'"
            " ORDER BY version DESC LIMIT 1")
        publication = cur.fetchone()
    assert source is not None and float(source[0]) == pytest.approx(1.36)
    assert "1.36" in str(source[1])
    assert publication is not None
    evidence = publication[0]
    assert evidence["authority"][0]["authority_id"] == \
        "tri-2026-05-04-return-of-capital-v1"
    assert evidence["authority"][0]["record_sha256"] == \
        "5d485827600bfd9d25a3a6c840921346204d1841decb41f9a17c93d8a92c63ee"


def test_existing_v6_stale_bar_is_reearned_through_v7_semantic_replay(conn):
    _seed(conn)
    with conn.cursor() as cur:
        # Reconstruct the economic shape of an appliance that had already
        # earned v6 before the A1 authority existed.
        cur.execute(
            "UPDATE sentinel_bars SET dividend_per_share=1.36"
            " WHERE ticker='TRI' AND session=%s", (EVENT_DAY,))
        cur.execute(
            "DELETE FROM sentinel_processed_sessions WHERE cursor_name=%s",
            (maintenance.ACTIONS_CURSOR_NAME,))
    conn.commit()
    assert _tri_bar_dividend(conn) == pytest.approx(1.36)

    with store.corpus_write_lock(conn):
        cursor = maintenance.reconcile_actions_if_due(
            conn, fetch=tri_vendor(), through=END, force=True)

    assert cursor.kind == "sharadar-actions-export-reconcile/v7"
    assert _tri_bar_dividend(conn) == pytest.approx(1.435518)
    with conn.cursor() as cur:
        cur.execute("SELECT MAX(version) FROM sentinel_corpus_publications")
        current = int(cur.fetchone()[0])
    assert cursor.publication_version == current


def test_production_ingest_refuses_a_flagged_contradictory_source_amount(conn):
    with pytest.raises(CAA.CorporateActionAuthorityRefused,
                       match="matches neither reviewed stale"):
        _seed(conn, cash="1.40")
