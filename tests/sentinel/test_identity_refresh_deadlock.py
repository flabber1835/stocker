"""Regression matrix for the stale-listing/SEP-CDC identity deadlock."""
from __future__ import annotations

from contextlib import contextmanager
import datetime as dt
import inspect
from types import SimpleNamespace

import pytest

from sentinel.feed import (
    authority, coherence, identity_refresh, ingest, maintenance,
    publication as P, recovery, sep_reconciliation,
    store as S, tickers_authority, universe as U)
from tests.support.postgres import _EphemeralPostgres


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
        cur.execute("SELECT tablename FROM pg_tables WHERE schemaname='public'")
        for (table,) in cur.fetchall():
            cur.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
    c.commit()
    S.migrate_schema(c)
    yield c
    c.close()


def _row(permaticker: str, ticker: str, first: str, last: str, *,
         sector: str = "Industrials") -> dict:
    return {
        "table": "SEP",
        "permaticker": permaticker,
        "ticker": ticker,
        "category": "Domestic Common Stock",
        "sector": sector,
        "relatedtickers": "",
        "firstpricedate": first,
        "lastpricedate": last,
        "isdelisted": "N",
    }


def _published_yhnau_state(conn):
    rows = [
        _row("642732", "YHNAU", "2024-11-08", "2026-08-05"),
        _row("900001", "OTHER", "2020-01-01", "2026-08-21"),
    ]
    run = S.IngestRun(conn, "daily")
    U.write_universe(conn, rows, "2026-08-21", run_id=run.progress.run_id)
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO sentinel_bars"
            " (security_id,session,ticker,close_signal,close_unadjusted,"
            "  open_unadjusted,volume,last_written_run_id)"
            " VALUES (%s,%s,%s,10,10,10,1000,%s)",
            [
                ("642732", "2026-08-05", "YHNAU", run.progress.run_id),
                ("900001", "2026-08-21", "OTHER", run.progress.run_id),
            ])
    conn.commit()
    run.finish("success")
    P.publish(conn, run_id=run.progress.run_id)
    return rows


def _candidate(rows):
    out = [dict(row) for row in rows]
    out[0]["lastpricedate"] = "2026-08-25"
    return out


def _mutation(ticker="YHNAU", session="2026-08-21"):
    return [{
        "ticker": ticker,
        "date": session,
        "open": 11.04,
        "close": 11.04,
        "closeunadj": 11.04,
        "volume": 0.0,
        "lastupdated": "2026-08-25",
    }]


def _validate_args():
    return {
        "lo": dt.date(2026, 8, 24),
        "hi": dt.date(2026, 8, 25),
        "published_from": dt.date(2026, 8, 5),
        "published_through": dt.date(2026, 8, 21),
    }


def test_case_1_yhnau_forward_extension_resolves_without_rewriting_history(conn):
    published = _published_yhnau_state(conn)
    current = _candidate(published)

    with pytest.raises(identity_refresh.SepMutationIdentityRefused) as caught:
        identity_refresh.validate_sep_mutation_rows(
            conn, _mutation(), **_validate_args())
    assert caught.value.reason_code == "IDENTITY_INTERVAL_GAP"

    U.assert_candidate_listing_history_safe(
        conn, payload=identity_refresh._candidate_payload(current))
    resolver = identity_refresh.resolver_with_candidate(conn, current)
    assert resolver.resolve("YHNAU", "2026-08-21") == "642732"

    dates = identity_refresh.validate_sep_mutation_rows(
        conn, _mutation(), resolver=resolver, **_validate_args())
    assert dates == ["2026-08-21"]


def test_case_2_genuine_unknown_ticker_hard_fails(conn):
    published = _published_yhnau_state(conn)
    current = _candidate(published)

    def fetch(table, params=None, **kwargs):
        return iter([dict(row) for row in current])

    with pytest.raises(identity_refresh.SepMutationIdentityRefused) as caught:
        identity_refresh.validate_with_current_tickers_if_refreshable(
            conn, _mutation("MISSING"), fetch=fetch, **_validate_args())
    assert caught.value.reason_code == "NO_PERMANENT_ID"


def test_case_3_new_listing_after_published_frontier_is_safe(conn):
    published = _published_yhnau_state(conn)
    current = _candidate(published) + [
        _row("777777", "NEWCO", "2026-08-22", "2026-08-25")]
    U.assert_candidate_listing_history_safe(
        conn, payload=identity_refresh._candidate_payload(current))
    resolver = identity_refresh.resolver_with_candidate(conn, current)
    assert resolver.resolve("NEWCO", "2026-08-22") == "777777"


def test_case_4_historical_first_date_rewrite_hard_fails(conn):
    published = _published_yhnau_state(conn)
    current = _candidate(published)
    current[0]["firstpricedate"] = "2024-11-09"
    with pytest.raises(U.HistoricalIdentityMutation, match="firstpricedate"):
        U.assert_candidate_listing_history_safe(
            conn, payload=identity_refresh._candidate_payload(current))


def test_case_5_permaticker_reassignment_hard_fails(conn):
    published = _published_yhnau_state(conn)
    current = [dict(published[1]),
               _row("999999", "YHNAU", "2024-11-08", "2026-08-25")]
    with pytest.raises(U.HistoricalIdentityMutation):
        U.assert_candidate_listing_history_safe(
            conn, payload=identity_refresh._candidate_payload(current))


def test_case_6_ambiguous_ticker_reuse_is_rejected_structurally():
    rows = [
        _row("100", "ABC", "2020-01-01", "2026-08-25"),
        _row("200", "ABC", "2026-01-01", "2026-08-25"),
    ]
    with pytest.raises(
            tickers_authority.TickersStructureInvalid,
            match="nonoverlapping_ticker_reuse_intervals"):
        tickers_authority.validate(rows)


def test_case_7_unstable_current_tickers_is_never_refresh_authority(conn):
    published = _published_yhnau_state(conn)
    first = _candidate(published)
    second = _candidate(published)
    second[0]["lastpricedate"] = "2026-08-26"
    calls = {"n": 0}

    def fetch(table, params=None, **kwargs):
        calls["n"] += 1
        rows = first if calls["n"] == 1 else second
        return iter([dict(row) for row in rows])

    with pytest.raises(authority.VendorPublicationUnstable):
        identity_refresh.stable_current_tickers(fetch)


def test_case_8_failed_daily_publication_cannot_reach_cdc(monkeypatch):
    events = []

    @contextmanager
    def lock(_conn):
        yield

    monkeypatch.setattr(ingest, "_validate_source_before_run", lambda fetch: None)
    monkeypatch.setattr(
        ingest._impl.feed_store, "corpus_write_lock", lambda conn: lock(conn))
    monkeypatch.setattr(ingest, "_recover_before_run", lambda conn: None)
    monkeypatch.setattr(maintenance, "load_sep_cursor", lambda conn: object())
    monkeypatch.setattr(recovery, "failed_live_candidates", lambda conn: [])
    monkeypatch.setattr(
        ingest._impl.feed_store, "latest_visible_session",
        lambda conn: "2026-08-21")
    monkeypatch.setattr(
        coherence, "StableSharadarFetch",
        lambda fetch, after_session=None: fetch)
    monkeypatch.setattr(
        recovery, "extended_overlap_days", lambda conn, requested: requested)
    monkeypatch.setattr(
        ingest._impl, "_daily_locked",
        lambda *a, **k: SimpleNamespace(run_id="daily-candidate"))
    monkeypatch.setattr(
        ingest, "_finish_publication_or_refuse",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("publish failed")))
    monkeypatch.setattr(
        sep_reconciliation, "reconcile_next",
        lambda *a, **k: pytest.fail("key-set reconciliation must not run"))
    monkeypatch.setattr(
        maintenance, "reconcile_sep_mutations",
        lambda *a, **k: pytest.fail("CDC must not run"))

    with pytest.raises(RuntimeError, match="publish failed"):
        ingest.daily(object(), fetch=lambda *a, **k: (), today="2026-08-25")
    assert events == []


def test_case_9_safe_refresh_proof_runs_inside_postgres_read_only_transaction(conn):
    published = _published_yhnau_state(conn)
    current = _candidate(published)

    def fetch(table, params=None, **kwargs):
        return iter([dict(row) for row in current])

    conn.commit()
    with conn.cursor() as cur:
        cur.execute("BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
    dates, refresh = identity_refresh.validate_with_current_tickers_if_refreshable(
        conn, _mutation(), fetch=fetch, **_validate_args())
    assert dates == ["2026-08-21"]
    assert refresh is True
    conn.rollback()


def test_case_10_ambiguous_published_identity_never_attempts_refresh(monkeypatch):
    ambiguous = U.IdentityResolver([
        U.Listing("100", "ABC", "2020-01-01", "2026-08-25"),
        U.Listing("200", "ABC", "2020-01-01", "2026-08-25"),
    ])
    monkeypatch.setattr(U, "load_resolver", lambda conn: ambiguous)
    monkeypatch.setattr(
        identity_refresh, "stable_current_tickers",
        lambda *a, **k: pytest.fail("ambiguous identity must not refresh"))
    with pytest.raises(identity_refresh.SepMutationIdentityRefused) as caught:
        identity_refresh.validate_with_current_tickers_if_refreshable(
            object(), _mutation("ABC"), fetch=lambda *a, **k: (),
            **_validate_args())
    assert caught.value.reason_code == "AMBIGUOUS_IDENTITY"


def test_production_maintenance_facade_uses_typed_validator():
    assert maintenance._validate_sep_mutation_rows is (
        identity_refresh.validate_sep_mutation_rows)


def test_cdc_cursor_follows_correction_publication():
    source = inspect.getsource(maintenance._reconcile_sep_mutations_core)
    publication = source.index("published = _core.publication.publish")
    cursor = source.index("publication_version=published.version")
    assert publication < cursor
