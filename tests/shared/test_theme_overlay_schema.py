"""Schema tests for the portfolio-builder thematic overlay config.

Critical guarantee: the overlay is OFF by default, so existing strategies (and the
default builder config) behave exactly as before — the feature is fully opt-in and
revertible by config alone.
"""
import pytest
from pydantic import ValidationError

from stock_strategy_shared.schemas.strategy import PortfolioBuilderConfig, ThemeOverlayConfig


def test_overlay_off_by_default():
    pb = PortfolioBuilderConfig()
    assert pb.theme_overlay.enabled is False          # opt-in: no behavior change
    assert pb.theme_overlay.mode == "tilt"
    assert pb.theme_overlay.theme == "ai_infra"
    assert pb.theme_overlay.min_exposure == 0.35


def test_overlay_accepts_valid_config():
    cfg = ThemeOverlayConfig(enabled=True, mode="restrict", theme="ai_infra",
                             min_exposure=0.4, tilt_lambda=0.5)
    assert cfg.enabled and cfg.mode == "restrict" and cfg.tilt_lambda == 0.5


def test_overlay_rejects_unknown_mode():
    with pytest.raises(ValidationError):
        ThemeOverlayConfig(mode="boost")          # only tilt | restrict


def test_overlay_rejects_unknown_field():
    with pytest.raises(ValidationError):
        ThemeOverlayConfig(weight=0.5)            # extra="forbid"


@pytest.mark.parametrize("field,val", [
    ("min_exposure", -0.1), ("min_exposure", 1.5),
    ("tilt_lambda", -0.1),  ("tilt_lambda", 3.0),
])
def test_overlay_rejects_out_of_range(field, val):
    with pytest.raises(ValidationError):
        ThemeOverlayConfig(**{field: val})


def test_overlay_round_trips_in_portfolio_builder_config():
    pb = PortfolioBuilderConfig(theme_overlay={"enabled": True, "mode": "tilt", "tilt_lambda": 0.3})
    assert pb.theme_overlay.enabled is True
    assert pb.theme_overlay.tilt_lambda == 0.3
