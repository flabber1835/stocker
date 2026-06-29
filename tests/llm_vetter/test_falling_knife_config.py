"""Vetter resolves falling-knife thresholds from the strategy file, env as fallback.

A config that omits vetter.falling_knife (or a field) must reproduce the env value
exactly — byte-identical to the pre-migration env-only behaviour. A set field wins.
"""
import app.main as m
from stock_strategy_shared.schemas.strategy import FallingKnifeConfig

_ALL = ["backstop_pct", "window_days", "excess_pct", "beta_lookback",
        "vol_scaling", "vol_anchor", "excess_min", "excess_max"]
_GLOBAL = {
    "backstop_pct": "DRAWDOWN_BACKSTOP_PCT", "window_days": "DRAWDOWN_WINDOW_DAYS",
    "excess_pct": "DRAWDOWN_EXCESS_PCT", "beta_lookback": "DRAWDOWN_BETA_LOOKBACK",
    "vol_scaling": "DRAWDOWN_VOL_SCALING", "vol_anchor": "DRAWDOWN_VOL_ANCHOR",
    "excess_min": "DRAWDOWN_EXCESS_MIN", "excess_max": "DRAWDOWN_EXCESS_MAX",
}


def teardown_function(_):
    m._apply_falling_knife_config(None)   # restore env defaults for other tests


def test_none_falls_back_to_env():
    m._apply_falling_knife_config(None)
    for attr in _ALL:
        assert getattr(m, _GLOBAL[attr]) == m._ENV_FK[attr], attr


def test_empty_config_is_identical_to_env():
    m._apply_falling_knife_config(FallingKnifeConfig())  # all None
    for attr in _ALL:
        assert getattr(m, _GLOBAL[attr]) == m._ENV_FK[attr], attr


def test_set_field_overrides_env_others_fall_back():
    m._apply_falling_knife_config(FallingKnifeConfig(excess_pct=0.30, vol_scaling=False))
    assert m.DRAWDOWN_EXCESS_PCT == 0.30
    assert m.DRAWDOWN_VOL_SCALING is False
    # untouched fields still come from env
    assert m.DRAWDOWN_BACKSTOP_PCT == m._ENV_FK["backstop_pct"]
    assert m.DRAWDOWN_BETA_LOOKBACK == m._ENV_FK["beta_lookback"]


def test_zero_disable_value_is_honored_not_treated_as_unset():
    # excess_pct=0 disables the beta path — must be kept, NOT replaced by the env default.
    m._apply_falling_knife_config(FallingKnifeConfig(excess_pct=0.0))
    assert m.DRAWDOWN_EXCESS_PCT == 0.0
