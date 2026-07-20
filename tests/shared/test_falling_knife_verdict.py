"""falling_knife_verdict — THE shared exclude/keep decision.

The whole point: the live vetter and the backtest engine now call THIS one
function, so the wind-tunnel veto is provably the live veto. These tests pin the
two-trigger logic and, critically, replicate BOTH callers' old inline decision
code and assert it agrees with the shared verdict across a fuzzed grid — the
behavior-preserving proof for the extraction.
"""
import itertools

import pytest

from stock_strategy_shared.drawdown import falling_knife_verdict, scaled_excess_threshold

FK = dict(excess_pct=0.15, backstop_pct=0.25, vol_scaling=True,
          vol_anchor=0.35, excess_min=0.10, excess_max=0.30)


def _v(raw, exc, idio, **over):
    return falling_knife_verdict(raw, exc, idio, **{**FK, **over})


# ── the two triggers ──────────────────────────────────────────────────────────

def test_excess_trigger_fires_and_wins_ties():
    # excess -20% past the vol-scaled limit; excess wins the trigger label
    out = _v(-0.30, -0.20, 0.35)
    assert out["excluded"] is True and out["trigger"] == "excess"
    assert out["excess_limit"] == pytest.approx(0.15)   # σ=anchor → base


def test_absolute_floor_fires_when_no_beta_path():
    # no excess number (data-poor) but a 30% raw collapse → absolute floor
    out = _v(-0.30, None, None)
    assert out["excluded"] is True and out["trigger"] == "absolute"


def test_data_gap_exemption_keeps():
    assert _v(None, None, None)["excluded"] is False
    assert _v(None, None, None)["trigger"] is None


def test_moderate_market_driven_drop_is_kept():
    # big raw drop but tiny idiosyncratic excess → market dragged it, not a knife
    out = _v(-0.22, -0.05, 0.35)
    assert out["excluded"] is False and out["trigger"] is None


def test_vol_scaling_tightens_calm_names():
    # calm name (low idio_vol) gets a tighter limit → a smaller excess trips it
    out = _v(-0.14, -0.11, 0.20)                  # limit ≈ 0.15*0.20/0.35 ≈ 0.086, clamped to 0.10
    assert out["excess_limit"] == pytest.approx(0.10)
    assert out["excluded"] is True                # -0.11 <= -0.10


def test_disable_triggers():
    assert _v(-0.9, -0.9, 0.35, excess_pct=0, backstop_pct=0)["excluded"] is False
    assert _v(-0.30, -0.05, 0.35, excess_pct=0)["trigger"] == "absolute"  # only floor left


def test_vol_scaling_off_uses_flat_base():
    out = _v(-0.14, -0.16, 0.05, vol_scaling=False)
    assert out["excess_limit"] == pytest.approx(0.15)   # flat, ignores idio_vol
    assert out["excluded"] is True


# ── behavior-preserving proof: shared verdict == both callers' OLD inline code ──

def _old_vetter_decision(raw_dd, exc_dd, idio, fk):
    if fk["vol_scaling"] and fk["excess_pct"] > 0:
        excess_limit = scaled_excess_threshold(
            idio, fk["excess_pct"], anchor=fk["vol_anchor"],
            lo=fk["excess_min"], hi=fk["excess_max"])
    else:
        excess_limit = fk["excess_pct"]
    excess_hit = fk["excess_pct"] > 0 and exc_dd is not None and exc_dd <= -excess_limit
    absolute_hit = fk["backstop_pct"] > 0 and raw_dd is not None and raw_dd <= -fk["backstop_pct"]
    return (excess_hit or absolute_hit), excess_hit, excess_limit


@pytest.mark.parametrize("raw,exc,idio", itertools.product(
    [None, -0.02, -0.10, -0.15, -0.25, -0.40],
    [None, -0.05, -0.10, -0.15, -0.20, -0.35],
    [None, 0.05, 0.20, 0.35, 0.70, 1.40],
))
@pytest.mark.parametrize("vol_scaling", [True, False])
def test_shared_verdict_matches_old_inline_grid(raw, exc, idio, vol_scaling):
    fk = {**FK, "vol_scaling": vol_scaling}
    old_excluded, old_excess_hit, old_limit = _old_vetter_decision(raw, exc, idio, fk)
    v = falling_knife_verdict(raw, exc, idio, **fk)
    assert v["excluded"] == old_excluded
    assert (v["trigger"] == "excess") == old_excess_hit
    assert v["excess_limit"] == pytest.approx(old_limit)
