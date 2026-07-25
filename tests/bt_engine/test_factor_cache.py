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
    fp1 = data_fingerprint(prices, fnd, 5, "v1")
    fp2 = data_fingerprint(prices.iloc[:-10], fnd, 5, "v1")     # fewer rows / earlier max date
    assert fp1 != fp2


# ── the proof: cached sweep ≡ uncached sweep ─────────────────────────────────

def test_cached_sweep_bit_identical_to_uncached(tmp_path):
    prices, fnd, days, flip = _flip_data()
    w = _windows(days, flip)
    base = _base_cfg()

    plain = run_config_both_windows(prices, fnd, {}, base, {}, w, _SIM_KW)

    cache = FactorCache(data_fingerprint(prices, fnd, 6, "v1"), root=str(tmp_path))
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
    cache = FactorCache(data_fingerprint(prices, fnd, 6, "v1"), root=str(tmp_path))
    # warm the cache with the BASE config first, then run the diff config
    run_config_both_windows(prices, fnd, {}, base, {}, w, _SIM_KW, cache)
    cached = run_config_both_windows(prices, fnd, {}, base, diff, w, _SIM_KW, cache)

    assert cached.get("error_message") is None
    for window in ("in_sample", "out_sample"):
        assert cached[window] == plain[window]


# ── cache IDENTITY (audit item 1) ───────────────────────────────────────────
# The fingerprint used to hash only the SHAPE of the data — row counts, ticker
# count, price date span. None of that changes when data is CORRECTED IN PLACE,
# which is exactly what the SF1 re-backfill does: it writes market_cap and
# shares_outstanding onto EXISTING rows. Same keys, same counts, same span,
# byte-identical fingerprint, stale cache silently reused — and the coverage
# observer could not have caught it, because both factors are weight-0 in the
# active config and are therefore never observed.

def _same_shape_pair():
    """Two frames identical in every SHAPE dimension but different in VALUES —
    the in-place correction the old fingerprint could not see."""
    prices, fnd, _days, _flip = _flip_data(n_days=60, flip_at=50)
    corrected = fnd.copy()
    corrected["roe"] = corrected["roe"] * 2.0        # values changed, shape identical
    assert len(corrected) == len(fnd)
    return prices, fnd, corrected


def test_an_in_place_correction_changes_the_fingerprint_via_the_version():
    prices, before, after = _same_shape_pair()
    # Shape alone cannot distinguish them...
    assert data_fingerprint(prices, before, 5, "v1") == \
        data_fingerprint(prices, after, 5, "v1"), (
            "sanity: the shape components genuinely cannot see this change")
    # ...which is why the CORPUS VERSION is what invalidates.
    assert data_fingerprint(prices, before, 5, "v1") != \
        data_fingerprint(prices, after, 5, "v2")


def test_no_version_means_no_cache_rather_than_a_weak_key():
    """FAIL-CLOSED. Degrading to the shape hash would restore the exact bug;
    the cache is a pure optimization, so a wrong cache is worse than none."""
    prices, fnd, _days, _flip = _flip_data(n_days=60, flip_at=50)
    for missing in (None, ""):
        assert data_fingerprint(prices, fnd, 5, missing) is None


def test_the_shape_components_are_still_part_of_the_key():
    """Defence in depth: a corpus mutated by something that forgets to bump the
    version should still be likely to invalidate."""
    prices, fnd, _days, _flip = _flip_data(n_days=60, flip_at=50)
    assert data_fingerprint(prices, fnd, 5, "v1") != \
        data_fingerprint(prices.iloc[:-10], fnd, 5, "v1")
    assert data_fingerprint(prices, fnd, 5, "v1") != \
        data_fingerprint(prices, fnd, 6, "v1")
