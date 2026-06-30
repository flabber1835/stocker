"""Phase-1 evaluator packet: the pure cross-sectional IC helper + backfill iteration."""
from datetime import date

import pandas as pd
import pytest

import app.evaluator_packet as ep
from app.evaluator_packet import _spearman_ic


def test_ic_perfect_positive():
    s = pd.Series({f"T{i}": i for i in range(15)})
    f = pd.Series({f"T{i}": i * 0.01 for i in range(15)})
    ic, n = _spearman_ic(s, f)
    assert n == 15 and ic == 1.0


def test_ic_perfect_negative():
    s = pd.Series({f"T{i}": i for i in range(15)})
    f = pd.Series({f"T{i}": -i for i in range(15)})
    ic, n = _spearman_ic(s, f)
    assert ic == -1.0


def test_ic_too_few_obs_returns_none():
    s = pd.Series({f"T{i}": i for i in range(5)})
    f = pd.Series({f"T{i}": i for i in range(5)})
    ic, n = _spearman_ic(s, f)
    assert ic is None and n == 5


def test_ic_drops_nan_pairs():
    s = pd.Series({f"T{i}": i for i in range(15)})
    f = pd.Series({f"T{i}": (None if i % 2 else i) for i in range(15)})  # half NaN
    ic, n = _spearman_ic(s, f)
    assert n < 15 and (ic is None or ic == 1.0)  # surviving pairs still monotone


@pytest.mark.asyncio
async def test_backfill_iterates_distinct_prior_weeks(monkeypatch):
    calls = []

    async def _fake(engine, as_of, artifacts_path=""):
        calls.append(as_of)
        return True   # pretend every week wrote

    monkeypatch.setattr(ep, "maybe_write_weekly_packet", _fake)
    n = await ep.backfill_weekly_packets(None, date(2026, 7, 10), weeks=4)
    # strictly-prior, 7 days apart, distinct ISO weeks, count returned
    assert calls == [date(2026, 7, 3), date(2026, 6, 26), date(2026, 6, 19), date(2026, 6, 12)]
    assert len({c.isocalendar().week for c in calls}) == 4
    assert n == 4
