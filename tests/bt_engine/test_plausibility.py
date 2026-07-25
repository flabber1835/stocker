"""Output-plausibility guards for the simulator.

The existing suite tests MECHANICS — determinism, no-look-ahead, the knife, the
orphan timer, fill timing, that costs reduce equity. Every one of them passed
while the simulator returned -96% on a book whose every holding rose, because
nothing asserted the OUTPUT was arithmetically possible.

That number was never seen for four weeks: the experiment lane had never
completed a run, so no human ever read a finished figure. The loop being inert
and the numbers being unexamined were the same fact.

Root cause of that bug (regression-locked below): `last_seen`/`last_px` were
refreshed only inside `_mtm`, which walks HELD tickers. A name's timestamp
therefore froze the moment it left the book, and on re-entry weeks later the
stale timestamp tripped the delist sweep — instantly liquidating the fresh
position at the stale price. On an upward-drifting series the stale price is
lower, so every re-entry booked a guaranteed loss. Cost-independent, scaling
with rebalance frequency, compounding to -93%.
"""
import numpy as np
import pandas as pd
import pytest

from app.sim import run_simulation, SimParams

from .test_sim import _cfg

TICKERS = ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF", "SPY"]


def _rising(n_days=400, drift=0.0006, div_adjust=False):
    """Every ticker trends UP. Any long-only book must therefore make money —
    there is no selection skill to argue about.

    div_adjust mirrors the REAL Sharadar shape, where adjusted_close (split+div
    adjusted) differs from close (as-traded) by a ratio that drifts over time.
    The original fixtures set them equal, so that whole code path — including
    the adjusted-open conversion — was never exercised by any test.
    """
    days = pd.bdate_range("2024-01-02", periods=n_days)
    rows = []
    for k, t in enumerate(TICKERS):
        px = 100.0
        for i, d in enumerate(days):
            px *= 1.0 + drift + 0.002 * np.sin(i / 7.0 + k)
            f = (0.90 + 0.10 * i / (n_days - 1)) if div_adjust else 1.0
            rows.append({"ticker": t, "date": d, "open": px * 0.999, "close": px,
                         "adjusted_close": px * f, "volume": 1_000_000.0})
    fnd = pd.DataFrame([{"ticker": t, "as_of_date": days[0], "pe_ratio": 15.0,
                         "pb_ratio": 2.0, "roe": 0.15, "debt_to_equity": 0.5,
                         "revenue_growth": 0.05, "eps_growth": 0.05}
                        for t in TICKERS if t != "SPY"])
    return pd.DataFrame(rows), fnd, days


def _run(days, prices, fnd, **over):
    kw = dict(start=days[60].date(), end=days[-1].date(), tx_cost_bps=10,
              fill_timing="next_open", rebalance_every=5)
    kw.update(over)
    return run_simulation(prices, fnd, {}, _cfg(), SimParams(**kw))


@pytest.mark.parametrize("timing", ["close", "next_open"])
@pytest.mark.parametrize("rebalance_every", [1, 5, 20])
def test_a_book_of_only_rising_stocks_makes_money(timing, rebalance_every):
    """THE guard. Every ticker rises; a long-only book cannot lose. This failed
    at -92% to -99.7% across every one of these six cells."""
    prices, fnd, days = _rising()
    res = _run(days, prices, fnd, fill_timing=timing, rebalance_every=rebalance_every)
    total = res.summary["total_return"]
    bench = res.summary["benchmark_total_return"]
    assert total > 0, (
        f"long-only book of rising stocks returned {total:.2%} "
        f"(benchmark {bench:.2%}) — arithmetically impossible")
    # and it must stay in the same universe as its benchmark, not merely positive
    assert total > bench - 0.25, (
        f"book {total:.2%} trails benchmark {bench:.2%} by more than 25pp on "
        "data where every holding rose")


def test_plausible_with_realistic_adjusted_vs_raw_prices():
    """The fixtures set adjusted_close == close, so the adjusted-open conversion
    (open x adjusted_close/close) was never exercised. Real Sharadar data always
    has them diverging."""
    prices, fnd, days = _rising(div_adjust=True)
    res = _run(days, prices, fnd)
    assert res.summary["total_return"] > 0, res.summary


def test_reentered_ticker_is_not_instantly_delisted():
    """REGRESSION: the exact failure. A name that leaves the book and is bought
    again later must not be force-sold by the delist sweep on its entry day —
    a fill is proof the name printed."""
    prices, fnd, days = _rising()
    res = _run(days, prices, fnd, rebalance_every=5)
    trades = pd.DataFrame(res.trades)
    assert not trades.empty
    delists = trades[trades["reason"].str.startswith("delisted")]
    assert delists.empty, (
        "the delist sweep fired on names that are still printing daily:\n"
        f"{delists[['date', 'ticker', 'price', 'reason']].head(10)}")

    # no ticker may be bought and sold on the SAME day
    same_day = (trades.groupby(["date", "ticker"])["action"]
                .agg(lambda s: set(s)).reset_index())
    both = same_day[same_day["action"].apply(
        lambda a: bool({"entry", "buy_add"} & a) and bool({"exit"} & a))]
    assert both.empty, f"bought and liquidated on the same day:\n{both.head()}"


def test_transaction_costs_only_ever_reduce_return():
    """Sanity on the cost path: it was masked before because the delist bleed
    dwarfed it — 0bps and 10bps both returned about -93%, which should have
    been a red flag on its own."""
    prices, fnd, days = _rising()
    free = _run(days, prices, fnd, tx_cost_bps=0).summary["total_return"]
    costly = _run(days, prices, fnd, tx_cost_bps=50).summary["total_return"]
    assert costly < free, f"50bps ({costly:.2%}) did not cost more than 0bps ({free:.2%})"
    assert free - costly < 0.5, "cost impact implausibly large"
