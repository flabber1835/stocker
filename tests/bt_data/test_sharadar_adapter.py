"""Tests for the Sharadar→pipeline column-contract mapping.

These lock the field mapping so it can't silently drift from what the live
pipeline factor functions expect:
  prices       → ticker, date, adjusted_close, close, volume
  fundamentals → ticker, as_of_date, pe_ratio, pb_ratio, roe, debt_to_equity,
                 revenue_growth, eps_growth   (as_of_date = POINT-IN-TIME datekey)
"""
from app.sharadar_adapter import (  # noqa: E402
    MAX_MAGNITUDE, map_actions_row, map_sep_row, map_sf1_row,
    map_tickers_row, compute_growth,
)


# ── SEP prices ──────────────────────────────────────────────────────────────

def test_sep_maps_closeadj_to_adjusted_close():
    row = {"ticker": "AAPL", "date": "2023-01-03", "open": 130, "high": 131,
           "low": 129, "close": 130.5, "closeadj": 129.8, "volume": 1000000}
    m = map_sep_row(row)
    assert m["ticker"] == "AAPL"
    assert m["date"] == "2023-01-03"
    assert m["adjusted_close"] == 129.8   # closeadj, NOT close
    assert m["close"] == 130.5
    assert m["volume"] == 1000000.0


def test_sep_handles_missing_values():
    m = map_sep_row({"ticker": "X", "date": "2023-01-03", "closeadj": "", "volume": None})
    assert m["adjusted_close"] is None
    assert m["volume"] is None


def test_sep_drops_reverse_split_artifact_prices():
    # BINI-class reverse-split penny stock: backward-adjusted prices balloon to
    # 1e17+, overflow the NUMERIC column, and are useless. They must map to None
    # (adjusted_close None → the backfill skips the row) rather than crash-insert.
    row = {"ticker": "BINI", "date": "2018-10-24",
           "open": 4.5e17, "high": 4.68e17, "low": 4.21e17,
           "close": 4.25e17, "closeadj": 4.25e17, "volume": 0}
    m = map_sep_row(row)
    assert m["adjusted_close"] is None
    assert m["open"] is None and m["close"] is None


def test_sep_keeps_high_but_legit_prices():
    # a genuinely expensive stock (BRK.A-scale, ~$700k) is well under the cap
    row = {"ticker": "BRK.A", "date": "2023-01-03", "close": 700000.0,
           "closeadj": 700000.0, "volume": 100}
    m = map_sep_row(row)
    assert m["adjusted_close"] == 700000.0
    assert MAX_MAGNITUDE > 700000.0


def test_sep_contract_has_exactly_pipeline_columns():
    m = map_sep_row({"ticker": "X", "date": "2023-01-03", "close": 1, "closeadj": 1, "volume": 1})
    # the pipeline reads: ticker, date, adjusted_close, close, volume
    for col in ("ticker", "date", "adjusted_close", "close", "volume"):
        assert col in m


# ── SF1 fundamentals (point-in-time) ──────────────────────────────────────────

def test_sf1_uses_datekey_as_point_in_time_asof():
    row = {"ticker": "MSFT", "datekey": "2023-04-25", "calendardate": "2023-03-31",
           "dimension": "ARQ", "pe": 30.0, "pb": 12.0, "roe": 0.40, "de": 0.5,
           "revenue": 52000, "eps": 2.45}
    m = map_sf1_row(row)
    # as_of_date is the FILING date (datekey), not the fiscal period end —
    # this is what prevents look-ahead bias.
    assert m["as_of_date"] == "2023-04-25"
    assert m["pe_ratio"] == 30.0
    assert m["pb_ratio"] == 12.0
    assert m["roe"] == 0.40
    assert m["debt_to_equity"] == 0.5
    # growth left None for the caller to compute from successive filings
    assert m["revenue_growth"] is None
    assert m["eps_growth"] is None
    # raw helpers carried for the caller's YoY computation
    assert m["_revenue"] == 52000.0
    assert m["_eps"] == 2.45


def test_sf1_without_datekey_is_dropped():
    assert map_sf1_row({"ticker": "X", "pe": 10}) is None


def test_sf1_fiscal_period_for_audit():
    m = map_sf1_row({"ticker": "X", "datekey": "2023-04-25",
                     "calendardate": "2023-03-31", "dimension": "ARQ"})
    assert m["fiscal_period"] == "2023-03-31/ARQ"


# ── Universe / tickers ─────────────────────────────────────────────────────────

def test_tickers_includes_common_stock_on_major_exchange():
    m = map_tickers_row({"ticker": "AAPL", "name": "Apple", "sector": "Technology",
                         "category": "Domestic Common Stock", "exchange": "NASDAQ"},
                        "2023-06-30")
    assert m is not None
    assert m["ticker"] == "AAPL"
    assert m["sector"] == "Technology"
    assert m["snapshot_date"] == "2023-06-30"


def test_tickers_excludes_etf_and_otc():
    assert map_tickers_row({"ticker": "SPY", "category": "ETF", "exchange": "NYSEARCA"},
                           "2023-06-30") is None
    assert map_tickers_row({"ticker": "XYZ", "category": "Domestic Common Stock",
                            "exchange": "OTC"}, "2023-06-30") is None


# ── YoY growth ─────────────────────────────────────────────────────────────────

def test_compute_growth_basic():
    assert compute_growth(110, 100) == 0.10
    assert compute_growth(90, 100) == -0.10


def test_compute_growth_none_when_missing_or_zero():
    assert compute_growth(None, 100) is None
    assert compute_growth(100, None) is None
    assert compute_growth(100, 0) is None


def test_compute_growth_negative_base_uses_abs():
    # year-ago was -50, now -25 → improvement; (−25 − −50)/|−50| = +0.5
    assert compute_growth(-25, -50) == 0.5


# ── ACTIONS (the authoritative corporate-action stream) ─────────────────────

def test_actions_maps_the_seven_columns():
    m = map_actions_row({"date": "2022-05-02", "action": "Merger",
                         "ticker": "bbb", "name": "Beta Inc", "value": 54.0,
                         "contraticker": "aaa", "contraname": "Alpha Co"})
    assert m == {"ticker": "BBB", "date": "2022-05-02", "action": "merger",
                 "name": "Beta Inc", "value": 54.0,
                 "contraticker": "AAA", "contraname": "Alpha Co"}


def test_actions_NEVER_COERCES_A_MISSING_VALUE_TO_ZERO():
    """THE load-bearing rule of this mapping.

    A delisting with no economic terms is the ordinary vendor case. Coercing its
    absent value to 0.0 turns "we do not know what this was worth" into "this
    was worth nothing" — a fabricated total loss. Downstream that is the
    difference between BLOCKING admissions and writing the position off, and in
    a 4%-of-equity strategy an invented zero permanently shrinks every position
    opened afterwards.
    """
    m = map_actions_row({"date": "2022-07-01", "action": "delisted",
                         "ticker": "DDD"})
    assert m["value"] is None, "absent terms must stay absent, never become 0.0"
    assert m["contraticker"] is None

    # ...and a STATED zero survives as a real zero, or the write-off path is
    # unreachable and the rule above is vacuous.
    stated = map_actions_row({"date": "2022-07-01", "action": "bankruptcy",
                              "ticker": "DDD", "value": 0})
    assert stated["value"] == 0.0


def test_actions_refuses_a_row_with_no_identity():
    """A row keyed on an empty ticker would collide with every other one."""
    assert map_actions_row({"date": "2022-01-01", "action": "split"}) is None
    assert map_actions_row({"ticker": "AAA", "action": "split"}) is None
    assert map_actions_row({"ticker": "AAA", "date": "2022-01-01"}) is None


def test_actions_keeps_every_type_including_the_unconsumed_ones():
    """Filtering at INGEST means discovering a needed action type costs another
    multi-hour fetch. dividend and ticker_change are already sequenced for use."""
    for act in ("split", "dividend", "ticker_change", "spinoff", "regulatory"):
        m = map_actions_row({"date": "2022-01-03", "action": act,
                             "ticker": "AAA"})
        assert m is not None and m["action"] == act


def test_action_dates_are_coerced_for_the_driver():
    """asyncpg rejects a str for a DATE column outright. The mapper tests pass
    happily while this path is broken, which is exactly how the bt_universe
    stage failed at the end of a multi-hour backfill."""
    import datetime as _dt

    from app.main import coerce_action_dates
    rows = coerce_action_dates([{"ticker": "AAA", "date": "2022-03-01",
                                 "action": "split"}])
    assert rows[0]["date"] == _dt.date(2022, 3, 1)


class TestTheUniverseStageIsReplayableAlone:
    """`permaticker` was mapped correctly and NULL in all 151,095 deployed rows,
    because the corpus predated the column. The Wealth Core loader keys on it
    (`WHERE permaticker IS NOT NULL`), so a 753-session rehearsal loaded ZERO
    securities, opened no position, and reported a 0% return as a SUCCESS.

    The mapping was never the bug. The bug was that fixing it required replaying
    a stage reachable only through /jobs/backfill, which redoes the ~35M-row
    price corpus first — hours, for a few thousand rows of metadata. A stage that
    expensive to replay is a stage nobody replays, which is how a column stays
    NULL for months after it is added.
    """

    import pathlib as _pathlib
    SRC = (_pathlib.Path(__file__).resolve().parents[2] / "services" / "bt-data"
           / "app" / "main.py").read_text()

    def test_the_stage_is_its_own_function(self):
        assert "async def _load_universe(" in self.SRC

    def test_it_has_its_own_endpoint(self):
        assert '@app.post("/jobs/backfill-universe")' in self.SRC

    def test_current_TICKERS_cannot_be_backdated(self):
        body = self.SRC[self.SRC.index("async def start_universe_backfill"):
                        self.SRC.index("# ── Data-depth report")]
        assert "if snap != today" in body
        assert "fabricate point-in-time evidence" in body

    def test_backdated_TICKERS_request_is_behaviorally_refused(self):
        import asyncio

        import pytest
        from fastapi import BackgroundTasks, HTTPException

        from app import main as bt_main

        with pytest.raises(HTTPException, match="point-in-time evidence") as exc:
            asyncio.run(bt_main.start_universe_backfill(
                BackgroundTasks(), snapshot_date="2023-12-29"))
        assert exc.value.status_code == 400

    def test_every_stage_that_can_gain_a_column_is_replayable_alone(self):
        """The general rule, not just this instance. Prices, fundamentals,
        actions and the universe have all gained mapped columns after their
        first ingest; each needs a way back that does not cost the corpus."""
        for endpoint in ("/jobs/backfill-prices", "/jobs/backfill-fundamentals",
                         "/jobs/backfill-actions", "/jobs/backfill-universe"):
            assert f'@app.post("{endpoint}")' in self.SRC, (
                f"{endpoint} missing — that stage can only be replayed by "
                f"redoing the whole price corpus")

    def test_the_full_backfill_still_runs_the_stage(self):
        """Extracting it must not remove it from the path that populates a fresh
        corpus."""
        body = self.SRC[self.SRC.index("async def _run_backfill("):
                        self.SRC.index("# In-process guard")]
        assert "_load_universe(" in body

    def test_the_upsert_rewrites_the_row_rather_than_skipping_it(self):
        """ON CONFLICT DO NOTHING would leave every existing row exactly as
        broken as it is now, and the re-run would report success.

        The conflict TARGET changed with the identity migration (2026-08-08):
        the key is `(snapshot_date, permaticker)`, so `permaticker` can no
        longer appear in the SET clause — it is the key, not an attribute. What
        must still hold is the original property: a replay REWRITES the mapped
        columns. `ticker` moved INTO the SET clause for the same reason, which
        is also what lets a security that changed symbol keep one row instead of
        forking into two."""
        upsert = self.SRC[self.SRC.index("async def _upsert_universe"):]
        upsert = upsert[:upsert.index("def coerce_action_dates")]
        assert "ON CONFLICT (snapshot_date, permaticker) DO UPDATE" in upsert
        assert "ticker=EXCLUDED.ticker" in upsert
        assert "first_price_date=EXCLUDED.first_price_date" in upsert
        assert "DO NOTHING" not in upsert

    def test_the_upsert_reports_what_it_PERSISTED_not_what_it_attempted(self):
        """The defect this whole migration was found through: `_upsert_universe`
        returned `len(rows)`, so 49,834 attempted against 21,733 stored read as
        unremarkable for months. A writer that cannot say what it stored cannot
        be audited."""
        upsert = self.SRC[self.SRC.index("async def _upsert_universe"):]
        upsert = upsert[:upsert.index("def coerce_action_dates")]
        assert "SELECT count(*) FROM bt_universe" in upsert, (
            "`persisted` must be MEASURED against the database, never echoed "
            "back from the input")
        for key in ("attempted", "distinct_identities", "persisted",
                    "rejected_no_permaticker", "duplicate_identity_collapsed"):
            assert f'"{key}"' in upsert, f"{key} missing from the write report"

    def test_the_mapper_reads_permaticker_from_the_vendor_row(self):
        from app.sharadar_adapter import map_tickers_row
        row = {"ticker": "AAPL", "name": "Apple Inc", "sector": "Technology",
               "category": "Domestic Common Stock", "exchange": "NASDAQ",
               "permaticker": 199059, "relatedtickers": "",
               "firstpricedate": "1980-12-12", "lastpricedate": "2026-08-03",
               "isdelisted": "N"}
        m = map_tickers_row(row, "2026-08-03")
        assert m["permaticker"] == "199059", (
            "a NULL here is what made the whole universe invisible")
