"""Last-known-good per-field fundamentals read (PBR incident, fix B).

The factor step no longer takes the latest fundamentals row verbatim: each
field independently takes its newest non-null value within FUND_LKG_WINDOW_DAYS,
so one degraded vendor refresh (total_assets nulled while every other field is
fine) is bridged by the previous good row instead of nulling quality for a week.
"""
import app.main as pm


def test_lkg_sql_covers_every_field_with_latest_non_null():
    sql = pm._lkg_fundamentals_sql()
    for f in pm.FUND_FIELDS:
        assert f"(ARRAY_REMOVE(ARRAY_AGG({f} ORDER BY as_of_date DESC), NULL))[1] AS {f}" in sql, f
    assert "MAX(as_of_date) AS as_of_date" in sql
    assert "GROUP BY ticker" in sql
    assert ":cutoff" in sql and ":tickers" in sql
    assert "source != 'no_data'" in sql


def test_lkg_field_list_matches_step5_dataframe_columns():
    # The DataFrame construction in Step 5 must consume exactly ticker, as_of_date,
    # then FUND_FIELDS in order — a drift here silently mislabels columns.
    import inspect
    src = inspect.getsource(pm._do_calculate) if hasattr(pm, "_do_calculate") else ""
    if not src:  # fall back: scan module source
        src = inspect.getsource(pm)
    expected = ('columns=["ticker", "as_of_date", "pe_ratio", "pb_ratio", "roe", "debt_to_equity",\n'
                '                     "revenue_growth", "eps_growth", "gross_profit", "total_assets",\n'
                '                     "shares_outstanding", "shares_outstanding_prior", "market_cap"]')
    assert list(pm.FUND_FIELDS) == ["pe_ratio", "pb_ratio", "roe", "debt_to_equity",
                                    "revenue_growth", "eps_growth", "gross_profit", "total_assets",
                                    "shares_outstanding", "shares_outstanding_prior", "market_cap"]
    assert expected.replace(" ", "").replace("\n", "") in src.replace(" ", "").replace("\n", "")


def test_window_default():
    assert pm.FUND_LKG_WINDOW_DAYS == 45
