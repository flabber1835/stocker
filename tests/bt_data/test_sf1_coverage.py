"""SF1 → bt_fundamentals / bt_earnings coverage fields.

These fields were always present in the SF1 rows bt-data already fetched; the
mapper simply dropped them. That made `small_cap` and `issuance` structurally
null in the wind tunnel — invisible in the score (both are weight-0 in the
active config) but NOT invisible in the universe: factor availability counts
weight-0 factors toward `min_non_null_factors`, so the tunnel ranked a narrower
set of tickers than live did on identical data.

The column NAMES are load-bearing: compute_small_cap / compute_issuance look
them up by name and return all-NaN for a missing column instead of raising, so a
rename would silently restore the bug.
"""
import pytest

from app.sharadar_adapter import map_sf1_earnings_row, map_sf1_row


def _row(**over) -> dict:
    base = {"ticker": "AAPL", "datekey": "2023-02-03",
            "calendardate": "2022-12-31", "dimension": "ARQ",
            "pe": 24.5, "pb": 40.1, "roe": 1.5, "de": 1.9,
            "marketcap": 2_400_000_000_000.0, "sharesbas": 15_800_000_000.0,
            "shareswa": 15_900_000_000.0, "revenue": 117_154_000_000.0,
            "eps": 1.88}
    base.update(over)
    return base


# ── field mapping ───────────────────────────────────────────────────────────

def test_market_cap_and_shares_are_mapped():
    m = map_sf1_row(_row())
    assert m["market_cap"] == pytest.approx(2_400_000_000_000.0)
    assert m["shares_outstanding"] == pytest.approx(15_800_000_000.0)


@pytest.mark.parametrize("cap", [1.0e12, 2.4e12, 3.9e12])
def test_a_mega_cap_market_cap_survives_the_magnitude_guard(cap):
    """CAUGHT IN REVIEW. `_f`'s MAX_MAGNITUDE of 1e12 is a RATIO guard (pe/pb
    from a near-zero denominator). Market cap is a LEVEL: Apple and Nvidia are
    legitimately $2-4e12, so routing them through _f would have silently nulled
    small_cap for exactly the largest, most-held names — the same silent-null
    failure this whole change exists to close, reintroduced one field over."""
    assert map_sf1_row(_row(marketcap=cap))["market_cap"] == pytest.approx(cap)


def test_absurd_levels_are_still_rejected():
    """The level guard is looser, not absent. $1e16 is bad data, not a company."""
    assert map_sf1_row(_row(marketcap=1e16))["market_cap"] is None
    assert map_sf1_row(_row(sharesbas=1e16, shareswa=None))["shares_outstanding"] is None


def test_ratio_fields_keep_the_tighter_ratio_guard():
    """Widening the level guard must not widen it for pe/pb — an explosive
    ratio from a near-zero denominator is exactly what that cap is for."""
    assert map_sf1_row(_row(pe=1e13))["pe_ratio"] is None


def test_column_names_match_the_live_fundamentals_contract():
    """compute_small_cap/compute_issuance do `if "market_cap" not in fund.columns:
    return all-NaN`. A rename here reintroduces the exact silent-null failure."""
    m = map_sf1_row(_row())
    for name in ("market_cap", "shares_outstanding", "shares_outstanding_prior"):
        assert name in m, name


def test_shares_falls_back_to_weighted_average():
    """sharesbas is the point-in-time count and the right first choice. shareswa
    is acceptable as a fallback because issuance is a RATIO of two consecutive
    filings — a consistent weighted-average basis still measures dilution."""
    m = map_sf1_row(_row(sharesbas=None))
    assert m["shares_outstanding"] == pytest.approx(15_900_000_000.0)


def test_missing_both_share_fields_is_null_not_zero():
    """Zero shares outstanding would make issuance compute a -100% figure out of
    thin air. Null is renormalized out; zero is a fabricated signal."""
    m = map_sf1_row(_row(sharesbas=None, shareswa=None))
    assert m["shares_outstanding"] is None


def test_prior_shares_is_left_for_the_caller():
    """It needs the year-ago FILING, a cross-row lookup that belongs in the
    backfill loop — the same split revenue_growth/eps_growth already use."""
    assert map_sf1_row(_row())["shares_outstanding_prior"] is None


# ── gross-profits-to-assets (the SILENT-FALLBACK gap) ───────────────────────
# Sharper than small_cap/issuance, which were merely null. Every strategy config
# in the repo sets quality_use_gross_profitability, and compute_quality falls
# back to ROE PER TICKER when gp/assets are missing — so the tunnel scored
# ROE-quality under a GPA config, at 25% of the composite, while `quality` came
# out fully populated and every non-null coverage check passed.

def test_gross_profit_and_total_assets_are_mapped():
    m = map_sf1_row(_row(gp=170_782_000_000.0, assets=346_747_000_000.0))
    assert m["gross_profit"] == pytest.approx(170_782_000_000.0)
    assert m["total_assets"] == pytest.approx(346_747_000_000.0)


@pytest.mark.parametrize("assets", [1.0e12, 3.4e12, 4.1e12])
def test_a_large_banks_total_assets_survives_the_magnitude_guard(assets):
    """The market_cap trap, one field over. `_f`'s 1e12 cap is a RATIO guard;
    total assets is a LEVEL, and JPMorgan's are legitimately ~$4e12. Routing it
    through _f would null the GPA denominator for exactly the largest names,
    silently dropping them back onto the ROE fallback."""
    assert map_sf1_row(_row(assets=assets))["total_assets"] == pytest.approx(assets)


def test_a_loss_making_quarters_negative_gross_profit_is_kept():
    """Negative gross profit is real and informative — it is the bottom of the
    quality ranking, not missing data. Discarding it would hand the ticker the
    ROE fallback instead, mixing two definitions inside one cross-section."""
    assert map_sf1_row(_row(gp=-1_200_000.0))["gross_profit"] == pytest.approx(-1_200_000.0)


def test_zero_gross_profit_is_kept_not_treated_as_missing():
    """`if not gp` would discard a genuine break-even quarter."""
    assert map_sf1_row(_row(gp=0.0))["gross_profit"] == 0.0


@pytest.mark.parametrize("over", [{"gp": None}, {"assets": ""}, {"assets": "n/a"}])
def test_absent_inputs_stay_null(over):
    m = map_sf1_row(_row(**over))
    assert m["gross_profit"] is None or m["total_assets"] is None


def test_the_gpa_column_names_match_what_compute_quality_looks_up():
    """compute_quality does `"gross_profit" in fund.columns` — a rename here does
    not raise, it silently restores the ROE fallback for the whole corpus."""
    m = map_sf1_row(_row())
    assert "gross_profit" in m and "total_assets" in m


def test_every_mapped_fundamentals_field_reaches_the_INSERT():
    """THE seam, and the one that would have caught this class at the source.

    gp/assets were not "mapped and mis-persisted" — they were never mapped at
    all. But the same gap one step later (mapped, then absent from the INSERT)
    is silent in exactly the same way: the mapper tests pass, the backfill
    succeeds, and the column is NULL forever. This pins mapper output against
    the INSERT column list in both directions.
    """
    import inspect
    import re

    from app import main as bt_main
    sql = inspect.getsource(bt_main._upsert_fundamentals)
    insert = re.search(r"INSERT INTO bt_fundamentals \((.*?)\)\s*\"?\s*\n?\s*\"?VALUES",
                       sql, re.S)
    assert insert, "could not locate the bt_fundamentals INSERT"
    cols = {c.strip() for c in re.sub(r'["\s]+', " ", insert.group(1)).split(",")
            if c.strip()}
    # The two raw levels are underscore-prefixed mapper scratch values, but are
    # now persisted as prior-quarter context for narrow incremental fetches.
    mapped = {k for k in map_sf1_row(_row()) if not k.startswith("_")}
    mapped.update({"revenue", "eps"})
    assert not (mapped - cols), \
        f"mapped but never persisted (silently NULL forever): {mapped - cols}"
    assert not (cols - mapped), \
        f"in the INSERT but never mapped (always NULL): {cols - mapped}"


def test_existing_fields_are_untouched():
    m = map_sf1_row(_row())
    assert (m["pe_ratio"], m["pb_ratio"], m["roe"], m["debt_to_equity"]) == \
        pytest.approx((24.5, 40.1, 1.5, 1.9))
    assert m["as_of_date"] == "2023-02-03"


# ── bt_earnings ─────────────────────────────────────────────────────────────

def test_earnings_row_separates_period_from_publication_date():
    """The whole no-look-ahead property rests on this distinction: the figure
    DESCRIBES Q4 2022 but only became KNOWN on the 2023-02-03 filing date."""
    e = map_sf1_earnings_row(map_sf1_row(_row()))
    assert e["fiscal_date_ending"] == "2022-12-31"   # period described
    assert e["reported_date"] == "2023-02-03"        # when it became public
    assert e["reported_eps"] == pytest.approx(1.88)


def test_earnings_reported_date_is_the_same_value_as_fundamentals_as_of():
    """map_sf1_earnings_row takes the MAPPED row, not the raw one, so both
    tables cannot disagree about when a filing became public. Two independent
    reads of `datekey` is the shape of the bug this work is closing."""
    m = map_sf1_row(_row())
    assert map_sf1_earnings_row(m)["reported_date"] == m["as_of_date"]


def test_no_estimated_eps_field_is_invented():
    """Sharadar carries no analyst estimate. Live's SUE is (reported − estimated)
    / stdev; fabricating an estimate would produce a number that looks like the
    live factor and is not. Absence is the honest representation."""
    e = map_sf1_earnings_row(map_sf1_row(_row()))
    assert "estimated_eps" not in e


@pytest.mark.parametrize("over", [{"eps": None}, {"calendardate": None},
                                  {"calendardate": ""}])
def test_unusable_earnings_rows_are_dropped(over):
    assert map_sf1_earnings_row(map_sf1_row(_row(**over))) is None


def test_zero_eps_is_kept_not_treated_as_missing():
    """A genuine break-even quarter is data. `if not eps` would discard it."""
    e = map_sf1_earnings_row(map_sf1_row(_row(eps=0.0)))
    assert e is not None and e["reported_eps"] == 0.0


# ── the backfill loop's year-ago anchor ─────────────────────────────────────

def test_prior_shares_uses_the_same_anchor_as_the_growth_fields():
    """Replicates the loop in main.py: rows[i-4] is the ~year-ago quarter. If
    prior shares used a different anchor than revenue_growth/eps_growth, issuance
    would measure a different period than everything beside it."""
    rows = [map_sf1_row(_row(datekey=f"202{y}-0{q}-01",
                             calendardate=f"202{y}-0{q}-28",
                             sharesbas=1000.0 + 100 * (4 * y + q)))
            for y in (1, 2) for q in (1, 2, 3, 4)]
    rows.sort(key=lambda r: r["as_of_date"])
    for i, r in enumerate(rows):
        prior = rows[i - 4] if i >= 4 else None
        r["shares_outstanding_prior"] = prior.get("shares_outstanding") if prior else None

    assert all(r["shares_outstanding_prior"] is None for r in rows[:4]), \
        "the first year has no year-ago filing to compare against"
    for i in range(4, len(rows)):
        assert rows[i]["shares_outstanding_prior"] == rows[i - 4]["shares_outstanding"]
        # 400 shares issued per year in this fixture → a positive dilution signal
        net = rows[i]["shares_outstanding"] / rows[i]["shares_outstanding_prior"] - 1
        assert net > 0


# ── point-in-time universe metadata (audit items 6/7) ───────────────────────
# TICKERS rows always carried firstpricedate/lastpricedate/isdelisted;
# map_tickers_row kept ticker/name/sector and discarded them, so the engine had
# ONE snapshot for all of history and inferred eligibility from price presence.

from app.sharadar_adapter import map_tickers_row  # noqa: E402


def _t(**over) -> dict:
    base = {"ticker": "AAPL", "name": "Apple Inc", "sector": "Technology",
            "category": "Domestic Common Stock", "exchange": "NASDAQ",
            "firstpricedate": "1980-12-12", "lastpricedate": "2026-07-24",
            "relatedtickers": "", "isdelisted": "N"}
    base.update(over)
    return base


def test_listing_window_and_delisted_flag_are_kept():
    m = map_tickers_row(_t(), "2026-07-25")
    assert m["first_price_date"] == "1980-12-12"
    assert m["last_price_date"] == "2026-07-24"
    assert m["is_delisted"] is False


@pytest.mark.parametrize("raw,expected", [
    ("Y", True), ("y", True), ("YES", True), ("TRUE", True), ("1", True),
    ("N", False), ("no", False), ("FALSE", False), ("0", False),
    (True, True), (False, False),
])
def test_isdelisted_parsing(raw, expected):
    assert map_tickers_row(_t(isdelisted=raw), "2026-07-25")["is_delisted"] is expected


def test_an_unparseable_delisted_flag_is_unknown_not_listed():
    """None means 'we do not know'. Defaulting to False would silently assert a
    delisted company is still trading."""
    assert map_tickers_row(_t(isdelisted="???"), "2026-07-25")["is_delisted"] is None
    assert map_tickers_row(_t(isdelisted=""), "2026-07-25")["is_delisted"] is None


def test_absent_last_price_date_stays_null_not_a_sentinel():
    """Empty lastpricedate is the NORMAL representation of 'still trading'. A
    sentinel date would delist every live company on that day."""
    m = map_tickers_row(_t(lastpricedate=""), "2026-07-25")
    assert m["last_price_date"] is None
    assert m["decision_metadata_complete"] is True


def test_authoritative_empty_and_absent_relatedtickers_are_distinguished():
    complete = map_tickers_row(_t(relatedtickers=""), "2026-07-25")
    incomplete_row = _t()
    incomplete_row.pop("relatedtickers")
    incomplete = map_tickers_row(incomplete_row, "2026-07-25")

    assert complete["related_tickers"] == []
    assert complete["decision_metadata_complete"] is True
    assert incomplete["related_tickers"] == []
    assert incomplete["decision_metadata_complete"] is False


def test_datetime_valued_dates_are_truncated_to_the_date():
    m = map_tickers_row(_t(firstpricedate="1980-12-12 00:00:00"), "2026-07-25")
    assert m["first_price_date"] == "1980-12-12"


@pytest.mark.parametrize("over", [
    {"category": "ETF"},
    {"category": None},
    {"exchange": "OTC"},
])
def test_snapshot_mapping_retains_ineligible_securities(over):
    """Eligibility is downstream; mapping is complete-snapshot evidence."""
    mapped = map_tickers_row(_t(**over), "2026-07-25")
    assert mapped is not None
    assert mapped["category"] == over.get("category", _t()["category"])
    assert mapped["exchange"] == over.get("exchange", _t()["exchange"])
    assert mapped["decision_metadata_complete"] is True


def test_absent_exchange_is_incomplete_rather_than_silently_filtered():
    row = _t()
    row.pop("exchange")
    mapped = map_tickers_row(row, "2026-07-25")
    assert mapped is not None
    assert mapped["exchange"] is None
    assert mapped["decision_metadata_complete"] is False


# ── DATE binding (the bug that failed a multi-hour backfill) ────────────────
# asyncpg rejects a str for a DATE column: "invalid input for query argument
# $5 ... ('str' object)". map_tickers_row returns ISO STRINGS, and the upsert
# must coerce every date column before binding. `snapshot_date` always was;
# first_price_date/last_price_date were added to the INSERT and not to the
# coercion, so bt_universe failed at the END of a full backfill.
#
# The mapper tests above all passed while this was broken — they check what the
# mapper RETURNS, not what reaches the driver. This checks the seam.

import datetime as _dt  # noqa: E402
import os as _os  # noqa: E402

# app.main refuses to import without a DSN (a deliberate fail-fast). These tests
# touch only the PURE coercion helper, so a dummy value is enough — no DB is
# opened at import time.
_os.environ.setdefault("BT_DATABASE_URL", "postgresql+asyncpg://u:p@127.0.0.1:1/x")

from app.main import coerce_universe_dates  # noqa: E402


def test_every_date_column_is_a_date_object_after_coercion():
    rows = [map_tickers_row(_t(), "2026-07-25")]
    assert isinstance(rows[0]["first_price_date"], str), (
        "precondition: the mapper emits ISO strings, which is why coercion exists")
    coerce_universe_dates(rows)
    for col in ("snapshot_date", "first_price_date", "last_price_date"):
        assert isinstance(rows[0][col], _dt.date), col


def test_coercion_preserves_nulls():
    """An absent lastpricedate means 'still trading'. Coercing it into some
    sentinel date would delist every live company."""
    rows = [map_tickers_row(_t(lastpricedate=""), "2026-07-25")]
    coerce_universe_dates(rows)
    assert rows[0]["last_price_date"] is None
    assert isinstance(rows[0]["first_price_date"], _dt.date)


def test_coercion_is_idempotent():
    """The upsert may be retried; feeding it already-coerced rows must not raise."""
    rows = [map_tickers_row(_t(), "2026-07-25")]
    coerce_universe_dates(rows)
    coerce_universe_dates(rows)
    assert isinstance(rows[0]["first_price_date"], _dt.date)


def test_the_insert_and_the_coercion_cover_the_same_date_columns():
    """THE regression. Adding a DATE column to the INSERT without adding it here
    is exactly what broke the backfill; this fails the next time it happens."""
    import inspect
    import re

    from app import main as bt_main
    sql = inspect.getsource(bt_main._upsert_universe)
    insert = re.search(r"INSERT INTO bt_universe \(([^)]*)\)", sql, re.S)
    assert insert, "could not locate the bt_universe INSERT"
    cols = {c.strip() for c in insert.group(1).replace('"', "").split(",") if c.strip()}
    date_cols = {c for c in cols if c.endswith("_date")}
    coerced = set(re.findall(r'"(\w+)"',
                             inspect.getsource(bt_main.coerce_universe_dates)))
    missing = date_cols - coerced
    assert not missing, f"DATE column(s) in the INSERT are never coerced: {missing}"


# ── replaying the SF1 stage on its own ──────────────────────────────────────
# Every column added to the mapping is NULL on existing rows until the stage
# runs again, and until 2026-08 the only way to re-run it was a full backfill —
# hours of price loading to fix columns prices have nothing to do with. That is
# how gross_profit/total_assets stayed missing long enough for the wind tunnel to
# score a quality factor live does not compute.

def test_the_sf1_stage_is_callable_without_the_price_stage():
    """A stage that cannot be replayed independently is a stage nobody replays."""
    from app import main as bt_main
    assert callable(getattr(bt_main, "_load_fundamentals", None))


def test_the_backfill_still_goes_through_the_same_function():
    """The extraction must not fork into two SF1 implementations — the endpoint
    and the full backfill have to write identical rows or a replay would
    silently differ from the original load."""
    import inspect

    from app import main as bt_main
    assert "_load_fundamentals(" in inspect.getsource(bt_main._run_backfill)
    assert "_load_fundamentals(" in inspect.getsource(
        bt_main.start_fundamentals_backfill)


def test_the_replay_endpoint_does_not_touch_prices():
    """The whole point. If this ever calls _run_backfill it becomes the
    multi-hour job it was written to avoid, and nobody would notice until they
    ran it."""
    import inspect

    from app import main as bt_main
    src = inspect.getsource(bt_main.start_fundamentals_backfill)
    assert "_run_backfill" not in src
    assert "_load_price_chunk" not in src


def test_the_fundamentals_upsert_is_non_destructive():
    """Re-running must UPDATE existing rows in place, never delete and reload:
    an interrupted replay would otherwise leave the corpus with a hole in it."""
    import inspect

    from app import main as bt_main
    src = inspect.getsource(bt_main._upsert_fundamentals)
    assert "ON CONFLICT (ticker, as_of_date) DO UPDATE" in src
    assert "DELETE" not in src.upper()


def test_it_shares_the_single_writer_guard():
    """Two long writers upserting the same table lock each other row by row —
    the 'five running tasks, zero progress' pileup the flag was added for."""
    import inspect

    from app import main as bt_main
    assert "_job_active" in inspect.getsource(bt_main.start_fundamentals_backfill)


# ── bt_universe: the same seam, for the Wealth Core fields ──────────────────
# `category`, `permaticker` and `related_tickers` were previously discarded by
# the mapper. Wealth Core decides common-equity membership from the raw category
# string and derives issuer identity from the other two — with no heuristic
# fallback, because a name or ticker-root guess merges unrelated companies and
# splits related ones.

def test_the_wealth_core_universe_fields_are_mapped():
    m = map_tickers_row(_t(category="ADR Common Stock", permaticker="199059",
                           relatedtickers="GOOGL GOOG"), "2026-07-25")
    assert m["category"] == "ADR Common Stock"
    assert m["permaticker"] == "199059"
    assert m["related_tickers"] == ["GOOG", "GOOGL"]      # sorted, deduped


def test_related_tickers_are_sorted_and_deduplicated():
    """The issuer key is a join of these, so an unstable order produces a
    different key for the same issuer on different rows — and the conflict check
    silently stops matching."""
    a = map_tickers_row(_t(relatedtickers="B,A,B"), "2026-07-25")["related_tickers"]
    b = map_tickers_row(_t(relatedtickers="A B"), "2026-07-25")["related_tickers"]
    assert a == b == ["A", "B"]


def test_absent_issuer_fields_stay_None_rather_than_becoming_empty_strings():
    """Wealth Core's strict mode REFUSES a security with no issuer identity. An
    empty string would pass a truthiness check and produce the key 'P:'."""
    m = map_tickers_row(_t(permaticker="", relatedtickers=""), "2026-07-25")
    assert m["permaticker"] is None and m["related_tickers"] == []


def test_every_mapped_universe_field_reaches_the_INSERT():
    """THE seam, and it caught a real gap: the three new fields were mapped but
    absent from the INSERT, so they would have stayed NULL forever while every
    mapper test passed."""
    import inspect
    import re

    from app import main as bt_main
    sql = inspect.getsource(bt_main._upsert_universe)
    ins = re.search(r"INSERT INTO bt_universe \((.*?)\)\s*\"?\s*\n?\s*\"?VALUES",
                    sql, re.S)
    assert ins, "could not locate the bt_universe INSERT"
    cols = {c.strip() for c in re.sub(r'["\s]+', " ", ins.group(1)).split(",")
            if c.strip()}
    mapped = set(map_tickers_row(_t(), "2026-07-25"))
    assert not (mapped - cols), f"mapped but never persisted: {mapped - cols}"
    assert not (cols - mapped), f"in the INSERT but never mapped: {cols - mapped}"


def test_completeness_provenance_is_rewritten_with_the_snapshot():
    import inspect
    from app import main as bt_main

    sql = inspect.getsource(bt_main._upsert_universe)
    assert "decision_metadata_complete=EXCLUDED.decision_metadata_complete" in sql


def test_related_tickers_are_flattened_before_binding():
    """A python list cannot bind to a TEXT column. Same class of failure as the
    date coercion that killed a multi-hour backfill at its final stage."""
    from app.main import coerce_universe_dates
    rows = [map_tickers_row(_t(relatedtickers="B A"), "2026-07-25")]
    coerce_universe_dates(rows)
    assert rows[0]["related_tickers"] == "A B"
