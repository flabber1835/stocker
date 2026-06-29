"""Correlation clustering — end-to-end against a REAL migrated Postgres.

Reproduces the "only a few tickers clustered" question. Seeds daily_prices with
three genuinely correlated groups plus two uncorrelated singletons, reads them back
with the portfolio-builder's own query, and runs the ACTUAL build_covariance +
correlation_clusters. Proves:

  - the clustering code clusters all correlated groups correctly when they are in
    the candidate pool (so the code is NOT regressed), and
  - clustering scopes to the candidate pool: a group absent from the pool is never a
    candidate and correctly shows no cluster — which is why the screener shows '—'
    for names outside the ranked candidate set.
"""
from __future__ import annotations

import os
import sys
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "services", "portfolio-builder"))
from app.select import build_covariance, correlation_clusters  # noqa: E402

pytestmark = pytest.mark.asyncio

SEMIS = ["AMAT", "LRCX", "MU", "NVDA"]    # correlated group A (semis)
POWER = ["CEG", "VST", "NRG"]             # correlated group B (power)
ENERGY = ["XOM", "CVX", "COP"]            # correlated group C (oil & gas)
SINGLETONS = ["AAPL", "KO"]               # uncorrelated loners
N = 200


def _seed_prices() -> list[tuple]:
    rng = np.random.default_rng(42)
    mkt = rng.normal(0, 0.008, N)         # weak shared market move

    def grp(tickers):
        gf = rng.normal(0, 0.018, N)      # group factor dominates → high within-corr
        return {t: 100.0 * np.exp(np.cumsum(0.3 * mkt + gf + rng.normal(0, 0.004, N)))
                for t in tickers}

    prices = {**grp(SEMIS), **grp(POWER), **grp(ENERGY),
              **{t: 100.0 * np.exp(np.cumsum(0.3 * mkt + rng.normal(0, 0.02, N)))
                 for t in SINGLETONS}}
    d0 = date(2026, 1, 1)
    return [(t, d0 + timedelta(days=i), round(float(v), 4))
            for t, px in prices.items() for i, v in enumerate(px)]


@pytest_asyncio.fixture
async def engine(async_dsn):
    eng = create_async_engine(async_dsn, future=True)
    async with eng.begin() as conn:
        await conn.execute(text("TRUNCATE daily_prices RESTART IDENTITY"))
        await conn.execute(
            text("INSERT INTO daily_prices (ticker, date, adjusted_close) "
                 "VALUES (:t, :d, :ac)"),
            [{"t": t, "d": d, "ac": ac} for t, d, ac in _seed_prices()],
        )
    yield eng
    await eng.dispose()


async def _prices_df(engine, only=None):
    """Read back via the portfolio-builder's query → long-format frame."""
    async with engine.connect() as conn:
        rows = await conn.execute(text(
            "SELECT ticker, date, adjusted_close FROM daily_prices ORDER BY ticker, date"))
        df = pd.DataFrame(rows.fetchall(), columns=["ticker", "date", "adjusted_close"])
    return df[df["ticker"].isin(only)] if only is not None else df


def _multi_member_clusters(raw_corr):
    cmap = correlation_clusters(raw_corr, threshold=0.70)
    sizes: dict[str, int] = {}
    for cid in cmap.values():
        sizes[cid] = sizes.get(cid, 0) + 1
    multi: dict[str, set] = {}
    for t, cid in cmap.items():
        if sizes[cid] > 1:
            multi.setdefault(cid, set()).add(t)
    singles = {t for t in cmap if sizes[cmap[t]] == 1}
    return [frozenset(m) for m in multi.values()], singles


class TestClusteringRealDB:
    async def test_full_pool_clusters_all_correlated_groups(self, engine):
        df = await _prices_df(engine)
        cov, dropped, raw_corr = build_covariance(df, window_days=252,
                                                  min_observations=126, shrinkage=0.20)
        assert dropped == []                       # 200 obs each → none dropped
        clusters, singles = _multi_member_clusters(raw_corr)
        # all three correlated groups form their own multi-member cluster
        assert frozenset(SEMIS) in clusters
        assert frozenset(POWER) in clusters
        assert frozenset(ENERGY) in clusters
        assert singles == set(SINGLETONS)          # loners get no cluster → '—'

    async def test_clustering_scopes_to_candidate_pool(self, engine):
        candidate_pool = SEMIS + POWER             # only these are candidates
        df = await _prices_df(engine, only=candidate_pool)
        cov, dropped, raw_corr = build_covariance(df, window_days=252,
                                                  min_observations=126, shrinkage=0.20)
        clusters, _ = _multi_member_clusters(raw_corr)
        assert frozenset(SEMIS) in clusters
        assert frozenset(POWER) in clusters
        # a group absent from the candidate pool is never a candidate → cannot cluster
        # (the screener's '—' on names outside the ranked candidate set, by design).
        assert all(t not in raw_corr.index for t in ENERGY)
        assert not any(c & set(ENERGY) for c in clusters)
