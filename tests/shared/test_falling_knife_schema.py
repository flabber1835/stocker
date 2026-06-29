"""FallingKnifeConfig: veto thresholds migrated into the validated strategy file.

Every field is Optional/None by default → a config omitting the block (or a field)
falls back to the service env value, i.e. byte-identical to the pre-migration setup.
Bounds are enforced so a pinned value can't be set to a nonsensical number.
"""
import pytest
from pydantic import ValidationError

from stock_strategy_shared.schemas.strategy import FallingKnifeConfig, VetterConfig


def test_all_fields_default_none():
    fk = FallingKnifeConfig()
    for attr in ("backstop_pct", "window_days", "excess_pct", "beta_lookback",
                 "vol_scaling", "vol_anchor", "excess_min", "excess_max"):
        assert getattr(fk, attr) is None, attr


def test_vetter_has_falling_knife_default():
    v = VetterConfig()
    assert isinstance(v.falling_knife, FallingKnifeConfig)
    assert v.falling_knife.excess_pct is None   # → env fallback


def test_values_round_trip_when_set():
    fk = FallingKnifeConfig(excess_pct=0.12, backstop_pct=0.30, beta_lookback=180,
                            vol_scaling=False, vol_anchor=0.40, window_days=21,
                            excess_min=0.08, excess_max=0.25)
    assert fk.excess_pct == 0.12 and fk.beta_lookback == 180 and fk.vol_scaling is False


@pytest.mark.parametrize("kwargs", [
    {"excess_pct": 1.5},      # > 1.0
    {"excess_pct": -0.1},     # < 0
    {"beta_lookback": 5},     # < 20
    {"window_days": 1},       # < 5
    {"vol_anchor": 0.0},      # not > 0
])
def test_out_of_bounds_rejected(kwargs):
    with pytest.raises(ValidationError):
        FallingKnifeConfig(**kwargs)


def test_unknown_field_rejected():
    with pytest.raises(ValidationError):
        FallingKnifeConfig(bogus=1)   # extra="forbid"
