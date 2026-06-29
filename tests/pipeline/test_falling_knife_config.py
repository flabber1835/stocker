"""Pipeline display mirror resolves falling-knife params the same way as the vetter,
so the screener card's excess_dd_limit never drifts from the actual veto trigger.
env is the fallback; a set strategy-file value wins.
"""
import app.main as m
from stock_strategy_shared.schemas.strategy import FallingKnifeConfig

_GLOBAL = {
    "window_days": "DRAWDOWN_WINDOW_DAYS", "beta_lookback": "BETA_LOOKBACK_DAYS",
    "excess_pct": "DRAWDOWN_EXCESS_PCT", "vol_scaling": "DRAWDOWN_VOL_SCALING",
    "vol_anchor": "DRAWDOWN_VOL_ANCHOR", "excess_min": "DRAWDOWN_EXCESS_MIN",
    "excess_max": "DRAWDOWN_EXCESS_MAX",
}


def teardown_function(_):
    m._apply_falling_knife_config(None)


def test_none_falls_back_to_env():
    m._apply_falling_knife_config(None)
    for attr, g in _GLOBAL.items():
        assert getattr(m, g) == m._ENV_FK[attr], attr


def test_set_field_overrides_env_others_fall_back():
    m._apply_falling_knife_config(FallingKnifeConfig(excess_pct=0.22, beta_lookback=200))
    assert m.DRAWDOWN_EXCESS_PCT == 0.22
    assert m.BETA_LOOKBACK_DAYS == 200
    assert m.DRAWDOWN_VOL_ANCHOR == m._ENV_FK["vol_anchor"]


def test_excess_dd_limit_uses_resolved_params():
    # vol-scaling off → the limit is exactly the resolved base, proving the resolver
    # feeds the display function.
    m._apply_falling_knife_config(FallingKnifeConfig(excess_pct=0.18, vol_scaling=False))
    assert m._excess_dd_limit(0.40) == 0.18
