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


def test_lkg_field_list_matches_the_dataframe_columns():
    """The SQL projection and the DataFrame's column labels must agree, or every
    fundamentals field is silently read off the wrong column.

    This used to be checked by string-matching a hardcoded `columns=[...]`
    literal against the source of `_do_calculate`. Both now derive from the one
    `FUND_FIELDS` tuple (`FUND_DF_COLUMNS`), so drift is structurally impossible
    rather than merely detected — assert the derivation, and that the field list
    itself has not changed shape underneath it."""
    import app.factor_inputs as fi

    assert list(pm.FUND_FIELDS) == ["pe_ratio", "pb_ratio", "roe", "debt_to_equity",
                                    "revenue_growth", "eps_growth", "gross_profit", "total_assets",
                                    "shares_outstanding", "shares_outstanding_prior", "market_cap"]
    assert fi.FUND_DF_COLUMNS == ["ticker", "as_of_date", *pm.FUND_FIELDS]
    # the projection order the SQL emits is ticker, as_of_date, then FUND_FIELDS
    sql = pm._lkg_fundamentals_sql()
    positions = [sql.index(f" AS {f}") for f in pm.FUND_FIELDS]
    assert positions == sorted(positions), "SQL emits fields out of FUND_FIELDS order"


def test_window_default():
    assert pm.FUND_LKG_WINDOW_DAYS == 45
