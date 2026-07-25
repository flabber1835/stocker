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
