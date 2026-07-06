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


import os
_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")


def test_marginal_ic_redundant_factor_drops_to_zero():
    n = 50
    a = pd.Series(range(n), dtype=float)            # a control
    dup = a.copy()                                  # factor identical to the control
    fwd = pd.Series(range(n), dtype=float)          # fwd correlates with a
    fs = pd.DataFrame({"a": a, "dup": dup})
    raw, _ = _spearman_ic(fs["dup"], fwd)
    mic, k = ep._marginal_ic(fs, "dup", ["a"], fwd)
    assert raw == 1.0                               # raw IC looks perfect…
    assert k == n and (mic is None or abs(mic) < 0.2)   # …but it ADDS nothing beyond `a`


def test_marginal_ic_independent_factor_survives():
    import numpy as np
    n = 60
    a = pd.Series(np.arange(n), dtype=float)
    indep = pd.Series(np.arange(n) % 7, dtype=float)    # ~uncorrelated with the ramp `a`
    fs = pd.DataFrame({"a": a, "indep": indep})
    mic, _ = ep._marginal_ic(fs, "indep", ["a"], fwd=indep)
    assert mic is not None and mic > 0.5               # genuine incremental signal kept


def test_marginal_ic_no_controls_returns_none():
    fs = pd.DataFrame({"x": pd.Series(range(20), dtype=float)})
    mic, k = ep._marginal_ic(fs, "x", [], fwd=pd.Series(range(20), dtype=float))
    assert mic is None and k == 0


def test_active_weighted_factors_from_live_config(monkeypatch):
    monkeypatch.setenv("STRATEGY_CONFIG_PATH",
                       os.path.join(_ROOT, "strategies", "momentum_rotation_v2.yaml"))
    w = ep._active_weighted_factors()
    assert "momentum" in w and "near_high" in w   # weighted in v2
    assert "issuance" not in w                     # weight 0 → not in the book


def test_regret_entries_carry_rank_and_fingerprint():
    """A deep-ranked missed winner (e.g. rank 509) must arrive with its rank and
    factor fingerprint, or the evaluator can notice it but never induce a
    codifiable thesis from recurring misses."""
    fs = pd.DataFrame(
        {"composite": [0.1, 0.9], "momentum": [0.2, 0.8],
         "near_high": [0.95, None], "volume_surge": [0.88, 0.1]},
        index=["DEEP", "NEAR"],
    )
    non_fwd = pd.Series({"DEEP": 0.42, "NEAR": 0.05, "GONE": 0.30})  # GONE not in fs
    rank_map = {"DEEP": 509, "NEAR": 12}

    entries = ep._regret_entries(non_fwd, rank_map, fs, top_n=3)

    assert [e["ticker"] for e in entries] == ["DEEP", "GONE", "NEAR"]  # sorted by fwd desc
    deep = entries[0]
    assert deep["rank"] == 509 and deep["fwd_return"] == 0.42
    fp = deep["factor_fingerprint"]
    assert fp["near_high"] == 0.95 and fp["volume_surge"] == 0.88  # dormant factors visible
    gone = entries[1]
    assert gone["rank"] is None and "factor_fingerprint" not in gone  # absent name degrades sanely
    near = entries[2]
    assert "near_high" not in near["factor_fingerprint"]  # nulls dropped, not zero-filled
