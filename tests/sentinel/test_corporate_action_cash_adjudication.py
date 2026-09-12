"""Independent PIT authority for disputed cash actions."""
from __future__ import annotations

import copy
from decimal import Decimal

import pytest

from sentinel.feed import corporate_action_authority as CAA
from sentinel.feed import actions_map, ingest, maintenance, sharadar, store
from sentinel.feed.domains import RawPriceDomainUnavailable
from stock_strategy_shared.wealth_core.sharadar_domains import raw_dividend_per_share
from sentinel.feed.source_authority.corporate_action_data import (
    CASH_ADJUDICATION_AUTHORITIES,
)
from tests.support.postgres import _EphemeralPostgres

EVENT_DAY = "2026-05-04"
END = "2026-05-08"
RATIO = Decimal("0.984560")
CASH_PER_NEW_SHARE = float(Decimal("1.435518") / RATIO)


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
    distribution = resolved.dividends[("TRI", EVENT_DAY)]
    assert distribution.cash_per_old_share == Decimal("1.435518")
    assert distribution.ordinary_split_adjusted_per_share == Decimal("0.25")
    assert raw_dividend_per_share(100, 100, distribution) == CASH_PER_NEW_SHARE + 0.25
    assert len(resolved.adjudications) == 1
    audit = resolved.adjudications[0]
    assert audit.disposition == "APPLIED"
    assert audit.source_amount == "1.36"
    assert audit.final_cash_amount == "1.435518"
    assert audit.source_content_sha256 == \
        CASH_ADJUDICATION_AUTHORITIES[0]["source_content_sha256"]
    assert audit.cash_entitlement_basis == "RAW_PRE_CONSOLIDATION_SHARE"
    assert Decimal(audit.new_shares_per_old_share) == RATIO


def test_source_convergence_is_accepted_without_double_correction():
    resolved = CAA.resolve_dividends([tri_action("1.435518")], [EVENT_DAY])
    assert raw_dividend_per_share(100, 100, resolved.dividends[("TRI", EVENT_DAY)]) == CASH_PER_NEW_SHARE
    assert resolved.adjudications[0].disposition == "SOURCE_CONVERGED"


def test_flagged_event_with_no_reviewed_authority_fails_closed():
    with pytest.raises(CAA.CorporateActionAuthorityRefused,
                       match="exactly one reviewed authority"):
        CAA.resolve_dividends([tri_action()], [EVENT_DAY], authorities=())


def test_flagged_event_with_third_unreviewed_amount_fails_closed():
    resolution = CAA.resolve_dividends([tri_action("1.40")], [EVENT_DAY])
    assert raw_dividend_per_share(100, 100, resolution.dividends[("TRI", EVENT_DAY)]) is None


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


@pytest.mark.parametrize("field,value", [
    ("cash_entitlement_basis", "RAW_POST_CONSOLIDATION_SHARE"),
    ("new_shares_per_old_share", "0"),
    ("new_shares_per_old_share", "NaN"),
])
def test_reviewed_authority_requires_a_usable_old_share_basis(field, value):
    record = copy.deepcopy(CASH_ADJUDICATION_AUTHORITIES[0])
    record[field] = value
    record["record_sha256"] = CAA.authority_record_sha256(record)
    with pytest.raises(CAA.CorporateActionAuthorityRefused):
        CAA.validate_authority(record)


def test_semantic_replay_scope_contains_the_combined_tri_event():
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
        cur.execute("DROP SCHEMA public CASCADE")
        cur.execute("CREATE SCHEMA public")
    connection.commit()
    store.migrate_schema(connection)
    yield connection
    connection.close()


def tri_vendor(*, cash="1.36", rebase=1):
    from sentinel.feed import calendar

    sessions = calendar.sessions_in_range("2026-04-20", END)
    action = tri_action(str(Decimal(cash) / Decimal(rebase)))
    split = {**tri_action("0.984560"), "action": "split"}

    def fetch(table, params=None, **_kwargs):
        params = dict(params or {})
        lo = str(params.get("date.gte", "0000-00-00"))
        hi = str(params.get("date.lte", "9999-99-99"))
        if table == sharadar.SEP:
            return [
                {"date": day, "ticker": "TRI", "close": str(Decimal(100) / Decimal(rebase)),
                 "closeunadj": "98.456" if day < EVENT_DAY else "100",
                 "open": str(Decimal(99) / Decimal(rebase)),
                 "volume": (984_560 if day < EVENT_DAY else 1_000_000) * rebase,
                 "lastupdated": day}
                for day in sessions if lo <= day <= hi
            ]
        if table == sharadar.ACTIONS:
            return [action, split] if lo <= EVENT_DAY <= hi else []
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
    assert _tri_bar_dividend(conn) == pytest.approx(CASH_PER_NEW_SHARE)

    with conn.cursor() as cur:
        cur.execute(
            "SELECT value,source_payload FROM sentinel_active_actions"
            " WHERE ticker='TRI' AND session=%s AND action='dividend'",
            (EVENT_DAY,))
        source = cur.fetchone()
        cur.execute(
            "SELECT evidence FROM sentinel_corpus_publications"
            " WHERE evidence->>'kind'='actions_economic_semantics_v9'"
            " ORDER BY version DESC LIMIT 1")
        publication = cur.fetchone()
    assert source is not None and float(source[0]) == pytest.approx(1.36)
    assert "1.36" in str(source[1])
    assert publication is not None
    evidence = publication[0]
    assert evidence["authority"][0]["authority_id"] == \
        "tri-2026-05-04-return-of-capital-v2"
    assert evidence["authority"][0]["record_sha256"] == \
        "7e8db148df1a136973871e800131aea7a6c127f1cb6afbd323109ea39b6e3df0"


def test_existing_stale_bar_is_reearned_through_current_semantic_replay(conn, monkeypatch):
    # Seed an actual v6 publication using its ordinary source economics. The
    # current database guards stay active throughout fixture setup and upgrade.
    with monkeypatch.context() as legacy:
        legacy.setattr(
            actions_map, "dividends_from_actions",
            lambda rows, sessions: CAA.resolve_dividends(
                rows, sessions, disputed_events=(), authorities=()).dividends)
        legacy.setattr(
            maintenance, "reconcile_actions_if_due",
            maintenance._core.reconcile_actions_if_due)
        _seed(conn)

    assert maintenance._core.load_actions_cursor(conn).kind == \
        "sharadar-actions-export-reconcile/v6"
    assert maintenance.load_actions_cursor(conn) is None
    assert _tri_bar_dividend(conn) == pytest.approx(1.36)

    with store.corpus_write_lock(conn):
        cursor = maintenance.reconcile_actions_if_due(
            conn, fetch=tri_vendor(), through=END, force=True)

    assert cursor.kind == "sharadar-actions-export-reconcile/v9"
    assert _tri_bar_dividend(conn) == pytest.approx(CASH_PER_NEW_SHARE)
    with conn.cursor() as cur:
        cur.execute("SELECT MAX(version) FROM sentinel_corpus_publications")
        current = int(cur.fetchone()[0])
    assert cursor.publication_version == current


def test_production_ingest_refuses_a_flagged_contradictory_source_amount(conn):
    with pytest.raises(RawPriceDomainUnavailable, match="cannot convert positive"):
        _seed(conn, cash="1.40")


def test_v8_correct_amount_wrong_basis_is_replayed_once_and_old_state_refused(conn, pg, monkeypatch):
    from datetime import date
    from sentinel.core.history import HistoryReconstructionRequired, require_history_compatible
    from sentinel.feed import publication

    def v8_dividends(rows, sessions):
        resolution = CAA.resolve_dividends(rows, sessions)
        return {key: getattr(value, "cash_per_old_share", value)
                for key, value in resolution.dividends.items()}

    with monkeypatch.context() as legacy:
        legacy.setattr(actions_map, "dividends_from_actions", v8_dividends)
        legacy.setattr(maintenance, "reconcile_actions_if_due",
                       maintenance._core.reconcile_actions_if_due)
        _seed(conn)
    prior = publication.require_current(conn)
    assert _tri_bar_dividend(conn) == 1.435518
    with store.corpus_write_lock(conn):
        maintenance._core._write_cursor(
            conn, name="sharadar-actions-export-reconcile:v8",
            kind="sharadar-actions-export-reconcile/v8", through=date.fromisoformat(END),
            publication_version=prior.version)
        assert maintenance.load_actions_cursor(conn) is None
        maintenance.reconcile_actions_if_due(conn, fetch=tri_vendor(), through=END)
    corrected = publication.require_current(conn)
    assert _tri_bar_dividend(conn) == CASH_PER_NEW_SHARE
    assert corrected.evidence["strategy_history"]["changes"][-1] == [corrected.version, EVENT_DAY]
    audit = corrected.evidence["adjudications"][0]
    assert audit["cash_entitlement_basis"] == "RAW_PRE_CONSOLIDATION_SHARE"
    assert Decimal(audit["new_shares_per_old_share"]) == RATIO
    assert float(audit["normalized_bar_dividend_per_share"]) == CASH_PER_NEW_SHARE

    # Reconnect to the durable cursor and force another unchanged publication.
    # The fixed basis survives restart; consumed v8 history remains invalid.
    with store.connect(pg.sync_dsn) as resumed:
        with store.corpus_write_lock(resumed):
            maintenance.reconcile_actions_if_due(
                resumed, fetch=tri_vendor(), through=END, force=True)
        repeated = publication.require_current(resumed)
        assert _tri_bar_dividend(resumed) == CASH_PER_NEW_SHARE
        with resumed.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM sentinel_corpus_publications"
                        " WHERE evidence->>'kind'='actions_economic_semantics_v9'")
            assert cur.fetchone()[0] == 1
        with pytest.raises(HistoryReconstructionRequired):
            require_history_compatible(
                prior_version=prior.version, last_processed_session=END,
                version=repeated.version, proof=repeated.evidence["strategy_history"])
        require_history_compatible(
            prior_version=corrected.version, last_processed_session=END,
            version=repeated.version, proof=repeated.evidence["strategy_history"])


def test_published_combined_event_reaches_canonical_ledger_after_database_restart(conn, pg):
    import json
    from sentinel.core.loader import load_window
    from sentinel.core.production import SessionState
    from stock_strategy_shared.wealth_core.ledger import Ledger
    from tests.sentinel.test_combined_event_economics import (
        NEXT, PRE, advance, held_seed, published,
    )

    _seed(conn)
    # Read actual normalized, published SQL rows with the production bar loader.
    # The held cut and reference-market tape are synthetic economic fixtures.
    with store.connect(pg.sync_dsn) as resumed:
        window = load_window(resumed, start=PRE, end=NEXT)
    config, seed = held_seed(window.bars_by_session[PRE])
    state = advance(seed, published(EVENT_DAY, window.bars_by_session[EVENT_DAY]), config)
    assert Ledger.from_dict(state.ledger).receivable_total() == pytest.approx(1435.518)
    assert state.wealth_core["episodes"]["0"]["current_shares"] == 984.56
    assert state.last_evidence["wealth_core"]["resolved_open_equity"] == pytest.approx(99006.958)
    settled = advance(SessionState.from_dict(json.loads(json.dumps(state.to_dict()))),
                      published(NEXT, window.bars_by_session[NEXT]), config)
    assert settled.wealth_core["cash"] == pytest.approx(1535.518)
    assert Ledger.from_dict(settled.ledger).receivable_total() == 0
