"""Issue #178 falsifiers for Sharadar publication authority.

These tests are deliberately source-facing. They prove that transport-successful
but incoherent reference data, historical session-local collapses, and listing
window corrections cannot silently become published authority.
"""
from __future__ import annotations

import asyncio
from datetime import date
from types import SimpleNamespace

import pytest

from sentinel import automation_runtime
from sentinel.automation.model import AutomationConfig
from sentinel.automation.service import AutomationService
from sentinel.feed import authority, coherence, publication, sharadar, store, universe
from tests.support.postgres import _EphemeralPostgres


def _ticker_row(ticker="AAA", permaticker="P-AAA", **updates):
    row = {
        "table": "SEP",
        "permaticker": permaticker,
        "ticker": ticker,
        "category": "Domestic Common Stock",
        "relatedtickers": "",
        "firstpricedate": "2000-01-03",
        "lastpricedate": "2026-08-14",
        "sector": "Technology",
        "isdelisted": "N",
    }
    row.update(updates)
    return row


def _sep_row(ticker="AAA", session="2026-08-14"):
    return {
        "ticker": ticker,
        "date": session,
        "close": 100.0,
        "closeunadj": 100.0,
        "open": 99.0,
        "volume": 1_000_000,
    }


def _counts(rows=5_000, *, identity=None, signal_close=None, raw_close=None,
            raw_open=None, volume=None):
    return coherence.SeedSessionCounts(
        rows=rows,
        identity=rows if identity is None else identity,
        signal_close=rows if signal_close is None else signal_close,
        raw_close=rows if raw_close is None else raw_close,
        raw_open=rows if raw_open is None else raw_open,
        volume=rows if volume is None else volume,
    )


class TestTickersAuthority:
    def test_every_strategy_relevant_persisted_field_is_fingerprinted(self):
        assert coherence.TICKERS_AUTHORITY_FIELDS == (
            "table", "permaticker", "ticker", "category", "relatedtickers",
            "firstpricedate", "lastpricedate", "sector", "isdelisted")

    def test_source_partition_is_required_not_defaulted_to_sep(self):
        row = _ticker_row()
        row.pop("table")
        with pytest.raises(coherence.TickerMetadataIncomplete,
                           match="table=SEP"):
            coherence.assert_tickers_metadata([row])

    def test_fresh_listing_dates_with_stale_strategy_metadata_refuse(self):
        first = _ticker_row(category="Domestic Common Stock")
        second = _ticker_row(category="ADR Common Stock")
        ticker_observation = 0

        def fetch(table, params=None, **_kwargs):
            nonlocal ticker_observation
            if table == sharadar.TICKERS:
                ticker_observation += 1
                return [first if ticker_observation == 1 else second]
            if table == sharadar.SEP:
                return [_sep_row()]
            return []

        guarded = coherence.StableSharadarFetch(fetch)
        guarded(sharadar.TICKERS)
        with pytest.raises(authority.VendorPublicationUnstable,
                           match="TICKERS publication is not stable"):
            guarded(sharadar.SEP, {
                "date.gte": "2026-08-14", "date.lte": "2026-08-14"})

    def test_partial_strategy_metadata_refuses_even_with_fresh_intervals(self):
        first = _ticker_row()
        second = _ticker_row(category=None)
        ticker_observation = 0

        def fetch(table, params=None, **_kwargs):
            nonlocal ticker_observation
            if table == sharadar.TICKERS:
                ticker_observation += 1
                return [first if ticker_observation == 1 else second]
            if table == sharadar.SEP:
                return [_sep_row()]
            return []

        guarded = coherence.StableSharadarFetch(fetch)
        guarded(sharadar.TICKERS)
        with pytest.raises(coherence.TickerMetadataIncomplete,
                           match="category"):
            guarded(sharadar.SEP, {
                "date.gte": "2026-08-14", "date.lte": "2026-08-14"})

    def test_null_and_empty_related_tickers_are_distinct_authority_states(self):
        sparse = coherence.observe_tickers([_ticker_row(relatedtickers=None)])
        empty = coherence.observe_tickers([_ticker_row(relatedtickers="")])
        with pytest.raises(authority.VendorPublicationUnstable):
            authority.require_stable("TICKERS", sparse, empty)

    def test_cursor_reordering_is_harmless_but_page_omission_is_not(self):
        rows = [_ticker_row("AAA", "P-AAA"),
                _ticker_row("BBB", "P-BBB")]
        first = coherence.observe_tickers(rows)
        authority.require_stable(
            "TICKERS", first, coherence.observe_tickers(list(reversed(rows))))
        with pytest.raises(authority.VendorPublicationUnstable):
            authority.require_stable(
                "TICKERS", first, coherence.observe_tickers(rows[:-1]))

    def test_sfp_closeadj_is_generation_authority(self):
        first = coherence.observe_sfp([
            {"ticker": "SPY", "date": "2026-08-14", "closeadj": 700.0}])
        second = coherence.observe_sfp([
            {"ticker": "SPY", "date": "2026-08-14", "closeadj": 701.0}])
        with pytest.raises(authority.VendorPublicationUnstable):
            authority.require_stable("SFP", first, second)


class TestHistoricalSeedCompleteness:
    @staticmethod
    def _sessions(monkeypatch):
        sessions = ["2026-08-12", "2026-08-13", "2026-08-14"]
        monkeypatch.setattr(
            coherence.calendar, "sessions_in_range",
            lambda _lo, _hi: list(sessions))
        return sessions

    def test_calibrated_clean_session_set_passes(self, monkeypatch):
        sessions = self._sessions(monkeypatch)
        coherence.assert_seed_history(
            {session: _counts() for session in sessions},
            date_from=sessions[0], date_to=sessions[-1])

    @pytest.mark.parametrize(("field", "value", "needle"), [
        ("identity", 4_900, "permanent identity"),
        ("raw_close", 4_900, "raw close"),
    ])
    def test_session_local_identity_or_price_collapse_refuses(
            self, monkeypatch, field, value, needle):
        sessions = self._sessions(monkeypatch)
        evidence = {session: _counts() for session in sessions}
        evidence[sessions[1]] = _counts(**{field: value})
        with pytest.raises(coherence.SeedHistoryIncomplete, match=needle):
            coherence.assert_seed_history(
                evidence, date_from=sessions[0], date_to=sessions[-1])

    def test_uniformly_small_but_internally_consistent_source_refuses(
            self, monkeypatch):
        sessions = self._sessions(monkeypatch)
        evidence = {session: _counts(rows=3_999) for session in sessions}
        with pytest.raises(coherence.SeedHistoryIncomplete,
                           match="calibrated full-source floor"):
            coherence.assert_seed_history(
                evidence, date_from=sessions[0], date_to=sessions[-1])

    def test_single_session_population_collapse_refuses(self, monkeypatch):
        sessions = self._sessions(monkeypatch)
        evidence = {
            sessions[0]: _counts(),
            sessions[1]: _counts(rows=4_400),
            sessions[2]: _counts(),
        }
        with pytest.raises(coherence.SeedHistoryIncomplete,
                           match="local median"):
            coherence.assert_seed_history(
                evidence, date_from=sessions[0], date_to=sessions[-1])

    def test_missing_exchange_session_refuses(self, monkeypatch):
        sessions = self._sessions(monkeypatch)
        evidence = {sessions[0]: _counts(), sessions[2]: _counts()}
        with pytest.raises(coherence.SeedHistoryIncomplete,
                           match="missing 1 exchange session"):
            coherence.assert_seed_history(
                evidence, date_from=sessions[0], date_to=sessions[-1])


class TestRetrySemantics:
    @pytest.mark.parametrize("exc", [
        coherence.TickerMetadataIncomplete("partial TICKERS"),
        coherence.SeedHistoryIncomplete("partial seed"),
        authority.VendorPublicationUnstable("moving source"),
        authority.FrontierDomainIncomplete("partial frontier"),
    ])
    def test_source_stabilization_refusals_retry_instead_of_latching(self, exc):
        assert not AutomationService._nonretryable(exc)

    def test_fenced_data_path_keeps_source_refusal_deployed_and_retryable(
            self, monkeypatch):
        """The #160 deployed/fenced path turns lag into DATA_NOT_READY, not BLOCKED."""
        runtime = object.__new__(automation_runtime.ProductionAutomation)
        runtime.automation_config = AutomationConfig()
        runtime._fenced_data_next_wake = None
        runtime._fenced_data_poll_seconds = 300

        class Conn:
            rollbacks = 0

            def rollback(self):
                self.rollbacks += 1

        conn = Conn()
        alerts = []
        monkeypatch.setattr(
            automation_runtime.schedule, "for_clock",
            lambda _now, _config: SimpleNamespace(
                decision_session=date(2026, 8, 18)))
        monkeypatch.setattr(
            automation_runtime.feed_store, "require_feed_schema",
            lambda _conn: None)
        monkeypatch.setattr(
            automation_runtime.schema, "require_runtime_schema",
            lambda _conn: None)
        monkeypatch.setattr(
            automation_runtime.feed_store, "latest_visible_session",
            lambda _conn: "2026-08-17")

        def refuse(_conn, *, today):
            assert today == "2026-08-18"
            raise coherence.TickerMetadataIncomplete(
                "TICKERS source publication still partial")

        monkeypatch.setattr(automation_runtime.ingest, "daily", refuse)
        monkeypatch.setattr(
            automation_runtime.outbox, "enqueue",
            lambda _conn, **kwargs: alerts.append(kwargs))

        wake = asyncio.run(runtime._fenced_data_wake(conn))

        assert wake == runtime._fenced_data_next_wake
        assert conn.rollbacks == 1
        assert len(alerts) == 1
        assert alerts[0]["event_type"] == "AUTOMATION_FENCED_DATA_NOT_READY"
        assert alerts[0]["severity"] == "WARN"
        assert alerts[0]["payload"]["state"] == "DEPLOYED_FENCED"
        assert alerts[0]["payload"]["readiness"] == "DATA_NOT_READY"
        assert "TickerMetadataIncomplete" in alerts[0]["payload"]["detail"]


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
        cur.execute("SELECT tablename FROM pg_tables WHERE schemaname='public'")
        for (table,) in cur.fetchall():
            cur.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
    connection.commit()
    store.migrate_schema(connection)
    yield connection
    connection.close()


class TestListingWindowCorrections:
    @staticmethod
    def _publish_universe(conn, *, snapshot, first=None, last=None,
                          relatedtickers=None):
        run = store.IngestRun(conn, "daily")
        run_id = run.progress.run_id
        row = {"ticker": "ABC", "permaticker": "P1",
               "firstpricedate": first, "lastpricedate": last}
        if relatedtickers is not None:
            row["relatedtickers"] = relatedtickers
        universe.write_universe(conn, [row], snapshot, run_id=run_id)
        run.finish("success")
        publication.publish(conn, run_id=run_id)
        return run_id

    def test_later_authority_can_narrow_both_listing_bounds(self, conn):
        self._publish_universe(
            conn, snapshot="2026-08-01",
            first="2000-01-03", last="2026-08-01")
        current = universe.load_resolver(conn)
        assert current.resolve("ABC", "2005-01-03") == "P1"
        assert current.resolve("ABC", "2024-01-03") == "P1"

        candidate = store.IngestRun(conn, "daily")
        run_id = candidate.progress.run_id
        universe.write_universe(
            conn,
            [{"ticker": "ABC", "permaticker": "P1",
              "firstpricedate": "2010-01-04",
              "lastpricedate": "2020-12-31"}],
            "2026-08-02", run_id=run_id)

        # Publication isolation: existing readers keep the old interval, while
        # the candidate resolver validates bars against the interval it would
        # make authoritative if publication succeeds.
        assert universe.load_resolver(conn).resolve("ABC", "2005-01-03") == "P1"
        proposed = universe.load_resolver(conn, include_run_id=run_id)
        assert proposed.resolve("ABC", "2005-01-03") is None
        assert proposed.resolve("ABC", "2015-01-05") == "P1"
        assert proposed.resolve("ABC", "2024-01-03") is None

        candidate.finish("success")
        publication.publish(conn, run_id=run_id)
        published = universe.load_resolver(conn)
        assert published.resolve("ABC", "2005-01-03") is None
        assert published.resolve("ABC", "2015-01-05") == "P1"
        assert published.resolve("ABC", "2024-01-03") is None

    def test_authoritative_empty_related_tickers_clears_but_null_carries(self,
                                                                          conn):
        self._publish_universe(
            conn, snapshot="2026-08-01", relatedtickers="BBB CCC")
        with conn.cursor() as cur:
            cur.execute("SELECT related_tickers FROM feed_universe_current")
            assert cur.fetchone()[0] == "BBB CCC"

        # Blank is observed evidence: no issuer siblings now. It must be able to
        # clear the old relationship rather than collapsing to SQL NULL.
        run = store.IngestRun(conn, "daily")
        universe.write_universe(
            conn,
            [{"ticker": "ABC", "permaticker": "P1", "relatedtickers": ""}],
            "2026-08-02", run_id=run.progress.run_id)
        run.finish("success")
        publication.publish(conn, run_id=run.progress.run_id)
        with conn.cursor() as cur:
            cur.execute("SELECT related_tickers FROM feed_universe_current")
            assert cur.fetchone()[0] == ""

        # True sparse/null observation carries the last known authoritative
        # empty set forward; it does not resurrect the old relationship.
        run = store.IngestRun(conn, "daily")
        universe.write_universe(
            conn,
            [{"ticker": "ABC", "permaticker": "P1", "relatedtickers": None}],
            "2026-08-03", run_id=run.progress.run_id)
        run.finish("success")
        publication.publish(conn, run_id=run.progress.run_id)
        with conn.cursor() as cur:
            cur.execute("SELECT related_tickers FROM feed_universe_current")
            assert cur.fetchone()[0] == ""
