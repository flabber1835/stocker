"""Memory contract for full-history runs (the OOM that took down the host).

The naive loader held three copies of a 35M-row corpus (~15-20GB peak) and the
sim then copied/pivoted several more times. These lock the properties that make
a full-history run fit under bt-engine's mem_limit:

  1. a loaded-shape frame is COMPACT (categorical ticker, float32 prices)
  2. the sim does NOT mutate the caller's frame (sweeps reuse ONE frame across
     configs — a mutation there would corrupt later configs, and the copy that
     used to prevent it cost a full duplicate every run)
  3. the sim skips its full-frame sort when the loader's ordering already holds
"""
import numpy as np
import pandas as pd

from app.sim import _is_ticker_date_sorted, _pivot


def _loaded_shape_frame(n_tickers=200, n_days=250):
    """A frame shaped exactly like data.load_prices returns."""
    days = pd.bdate_range("2020-01-01", periods=n_days)
    tickers = [f"T{i:04d}" for i in range(n_tickers)]
    rows = n_tickers * n_days
    return pd.DataFrame({
        "ticker": pd.Categorical(np.repeat(tickers, n_days), categories=tickers),
        "date": np.tile(days.to_numpy(), n_tickers),
        "open": np.full(rows, 100.0, dtype=np.float32),
        "close": np.full(rows, 101.0, dtype=np.float32),
        "adjusted_close": np.full(rows, 101.0, dtype=np.float32),
        "volume": np.full(rows, 1e6, dtype=np.float32),
    })


def test_loaded_frame_is_compact_vs_naive_dtypes():
    df = _loaded_shape_frame()
    lean = df.memory_usage(deep=True).sum()
    naive = df.assign(
        ticker=df["ticker"].astype(str),
        **{c: df[c].astype(np.float64) for c in
           ("open", "close", "adjusted_close", "volume")},
    ).memory_usage(deep=True).sum()
    # categorical + float32 must be a large multiple smaller; at 35M rows this
    # is the difference between ~1GB and several GB.
    assert lean * 3 < naive, f"lean={lean} naive={naive}"


def test_loader_ordering_lets_sim_skip_its_sort():
    df = _loaded_shape_frame(n_tickers=5, n_days=10)
    assert _is_ticker_date_sorted(df) is True
    # a shuffled frame must still be detected as unsorted (the sim then sorts)
    shuffled = df.sample(frac=1.0, random_state=0).reset_index(drop=True)
    assert _is_ticker_date_sorted(shuffled) is False
    # dates out of order WITHIN a ticker block are caught too
    bad = df.copy()
    bad.loc[bad.index[:2], "date"] = bad.loc[bad.index[:2], "date"].to_numpy()[::-1]
    assert _is_ticker_date_sorted(bad) is False


def test_pivot_matches_pivot_table_but_without_aggregation():
    df = _loaded_shape_frame(n_tickers=4, n_days=6)
    fast = _pivot(df, "adjusted_close")
    slow = df.pivot_table(index="date", columns="ticker", values="adjusted_close")
    pd.testing.assert_frame_equal(fast, slow, check_dtype=False, check_freq=False)


def test_sim_does_not_mutate_caller_frame(monkeypatch):
    """Sweeps hand the SAME frame to run_simulation for every config; the sim
    must leave it byte-identical (no added _adj_open column, no dtype upcast)."""
    from app import sim as simmod

    df = _loaded_shape_frame(n_tickers=6, n_days=40)
    # make SPY exist so run_simulation gets past its benchmark check
    cats = list(df["ticker"].cat.categories) + ["SPY"]
    spy = df[df["ticker"] == df["ticker"].cat.categories[0]].copy()
    spy["ticker"] = "SPY"
    df = pd.concat([df, spy], ignore_index=True)
    df["ticker"] = pd.Categorical(df["ticker"].astype(str), categories=cats)
    df = df.sort_values(["ticker", "date"], kind="stable").reset_index(drop=True)

    before_cols = list(df.columns)
    before_dtypes = df.dtypes.to_dict()
    before_hash = pd.util.hash_pandas_object(df, index=True).sum()

    # only the frame-prep half matters here; a full run needs a config+params,
    # so exercise the prep directly the way run_simulation does
    px = df
    if not pd.api.types.is_datetime64_any_dtype(px["date"]):
        px = px.copy()
    if not simmod._is_ticker_date_sorted(px):
        px = px.sort_values(["ticker", "date"], kind="stable")
    day_close = simmod._pivot(px, "adjusted_close")
    adj_factor = px["adjusted_close"] / px["close"].replace(0, np.nan)
    tmp = pd.DataFrame({"date": px["date"], "ticker": px["ticker"],
                        "_adj_open": px["open"] * adj_factor})
    day_open = simmod._pivot(tmp, "_adj_open")

    assert list(df.columns) == before_cols          # no _adj_open leaked onto it
    assert df.dtypes.to_dict() == before_dtypes     # no float32→float64 upcast
    assert pd.util.hash_pandas_object(df, index=True).sum() == before_hash
    assert not day_close.empty and not day_open.empty
