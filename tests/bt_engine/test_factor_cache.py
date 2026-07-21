"""Factor cache (audit perf #12) — cached sweeps must be BIT-IDENTICAL to
uncached ones, and the cache must invalidate itself when the data changes.

The memo's correctness premise: per rebalance date the factor frame depends
only on (as_of_date, factor_engine config, loaded data). The equivalence test
is the proof that threading the cache through changed nothing.
"""
from datetime import date

import pytest

from app.factor_cache import FactorCache, data_fingerprint, factor_cfg_key
from app.sweep import SweepWindows, run_config_both_windows
from tests.bt_engine.test_sweep import _SIM_KW, _base_cfg, _flip_data, _windows


# ── FactorCache unit behavior ────────────────────────────────────────────────

def test_roundtrip_and_hit_counting(tmp_path):
    import pandas as pd
    c = FactorCache("fp1", root=str(tmp_path))
    df = pd.DataFrame({"ticker": ["A"], "momentum": [0.5]})
    assert c.get(date(2026, 1, 2), "k1") is None          # miss
    c.put(date(2026, 1, 2), "k1", df)
    got = c.get(date(2026, 1, 2), "k1")                   # hit
    assert got is not None and got.equals(df)
    assert c.hits == 1 and c.misses == 1


def test_fingerprint_change_wipes_stale_entries(tmp_path):
    import pandas as pd
    c1 = FactorCache("fp1", root=str(tmp_path))
    c1.put(date(2026, 1, 2), "k1", pd.DataFrame({"x": [1]}))
    # data topped up → new fingerprint → old frames must not survive
    c2 = FactorCache("fp2", root=str(tmp_path))
    assert c2.get(date(2026, 1, 2), "k1") is None
    # same fingerprint again later does NOT wipe
    c3 = FactorCache("fp2", root=str(tmp_path))
    c3.put(date(2026, 1, 3), "k1", pd.DataFrame({"x": [2]}))
    assert FactorCache("fp2", root=str(tmp_path)).get(date(2026, 1, 3), "k1") is not None


def test_corrupted_entry_degrades_to_miss(tmp_path):
    c = FactorCache("fp1", root=str(tmp_path))
    p = c._path(date(2026, 1, 2), "k1")
    p.write_bytes(b"not a pickle")
    assert c.get(date(2026, 1, 2), "k1") is None


def test_unwritable_root_disables_cache_without_failing():
    c = FactorCache("fp1", root="/proc/definitely/not/writable")
    import pandas as pd
    c.put(date(2026, 1, 2), "k1", pd.DataFrame({"x": [1]}))   # no raise
    assert c.get(date(2026, 1, 2), "k1") is None


def test_factor_cfg_key_stable_and_config_sensitive():
    a = factor_cfg_key({"momentum_method": "residual", "w": 1})
    b = factor_cfg_key({"w": 1, "momentum_method": "residual"})   # order-insensitive
    c = factor_cfg_key({"momentum_method": "residual_riskadj", "w": 1})
    assert a == b and a != c


def test_data_fingerprint_changes_on_topup():
    prices, fnd, _days, _flip = _flip_data(n_days=60, flip_at=50)
    fp1 = data_fingerprint(prices, fnd, 5)
    fp2 = data_fingerprint(prices.iloc[:-10], fnd, 5)     # fewer rows / earlier max date
    assert fp1 != fp2


# ── the proof: cached sweep ≡ uncached sweep ─────────────────────────────────

def test_cached_sweep_bit_identical_to_uncached(tmp_path):
    prices, fnd, days, flip = _flip_data()
    w = _windows(days, flip)
    base = _base_cfg()

    plain = run_config_both_windows(prices, fnd, {}, base, {}, w, _SIM_KW)

    cache = FactorCache(data_fingerprint(prices, fnd, 6), root=str(tmp_path))
    cold = run_config_both_windows(prices, fnd, {}, base, {}, w, _SIM_KW, cache)
    assert cache.hits == 0 and cache.misses >= 1          # first pass populates
    warm = run_config_both_windows(prices, fnd, {}, base, {}, w, _SIM_KW, cache)
    assert cache.hits > 0                                 # second pass consumes

    for r in (cold, warm):
        assert r.get("error_message") is None
        for window in ("in_sample", "out_sample"):
            assert r[window] == plain[window], f"{window} diverged under cache"


def test_distinct_factor_configs_do_not_share_entries(tmp_path):
    """A diff that CHANGES factor output (momentum short window) must not read
    the base config's cached frames — the key is the factor-config identity."""
    prices, fnd, days, flip = _flip_data()
    w = _windows(days, flip)
    base = _base_cfg()
    diff = {"factor_engine.momentum_short_window": 10}

    plain = run_config_both_windows(prices, fnd, {}, base, diff, w, _SIM_KW)
    cache = FactorCache(data_fingerprint(prices, fnd, 6), root=str(tmp_path))
    # warm the cache with the BASE config first, then run the diff config
    run_config_both_windows(prices, fnd, {}, base, {}, w, _SIM_KW, cache)
    cached = run_config_both_windows(prices, fnd, {}, base, diff, w, _SIM_KW, cache)

    assert cached.get("error_message") is None
    for window in ("in_sample", "out_sample"):
        assert cached[window] == plain[window]
