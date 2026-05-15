from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, Field, model_validator


class FactorWeights(BaseModel):
    momentum: float = Field(ge=0, le=1)
    quality: float = Field(ge=0, le=1)
    value: float = Field(ge=0, le=1)
    growth: float = Field(ge=0, le=1)
    low_volatility: float = Field(ge=0, le=1)
    liquidity: float = Field(default=0.0, ge=0, le=1)  # optional, default 0

    @model_validator(mode="after")
    def weights_sum_to_one(self) -> FactorWeights:
        total = (
            self.momentum + self.quality + self.value
            + self.growth + self.low_volatility + self.liquidity
        )
        if abs(total - 1.0) > 0.01:
            raise ValueError(f"Factor weights must sum to 1.0, got {total:.4f}")
        return self


class RegimeCondition(BaseModel):
    """Conditions that define when a regime is active."""
    spy_above_slow_sma: bool
    vol_above_threshold: bool


class RegimeDetectionConfig(BaseModel):
    """How to detect the current market regime from SPY data.

    Regime is determined by two independent dimensions:
      - Trend:      is SPY above or below its slow SMA?
      - Volatility: is SPY 20-day realized vol above the threshold?

    confirmation_days: both signals must have been consistent for this many
    consecutive trading days before a regime switch is accepted. Prevents
    flipping regimes on a single bad or noisy day.

    The regimes dict maps a name to a (trend, vol) condition pair.
    The factor_weights dict in StrategyConfig uses the same names as keys.
    """
    slow_sma: int = Field(default=200, ge=20, le=500)
    vol_window: int = Field(default=20, ge=5, le=63)
    vol_threshold: float = Field(default=0.20, gt=0, lt=1)  # annualized
    confirmation_days: int = Field(default=5, ge=1, le=21)
    regimes: dict[str, RegimeCondition]

    @model_validator(mode="after")
    def regimes_cover_all_combinations(self) -> RegimeDetectionConfig:
        conditions = {(r.spy_above_slow_sma, r.vol_above_threshold) for r in self.regimes.values()}
        required = {(True, False), (True, True), (False, True), (False, False)}
        missing = required - conditions
        if missing:
            raise ValueError(f"regime_detection.regimes is missing conditions: {missing}")
        return self


class UniverseConfig(BaseModel):
    source: str = "etf_holdings"
    etf_ticker: str = "IWV"
    min_price: float = 5.0
    min_avg_dollar_volume_20d: float = 20_000_000


class VetterConfig(BaseModel):
    candidate_count: int = Field(default=50, ge=5, le=200)
    conviction_max_boost: float = Field(default=0.25, ge=0.0, le=1.0)
    conviction_boosts: dict[str, float] = Field(
        default_factory=lambda: {"high": 0.25, "medium": 0.12, "low": 0.05, "none": 0.0}
    )


class PortfolioBuilderConfig(BaseModel):
    method: Literal["greedy_score_per_port_vol"] = "greedy_score_per_port_vol"
    candidate_count: int = Field(default=100, ge=10, le=500)
    max_positions: int = Field(default=30, ge=1, le=100)
    covariance_window_days: int = Field(default=252, ge=20, le=504)
    min_covariance_observations: int = Field(default=126, ge=20, le=504)
    covariance_shrinkage: float = Field(default=0.20, ge=0.0, le=1.0)
    require_positive_composite_score: bool = False
    weighting: Literal[
        "equal_weight",
        "adj_score_proportional",
        "score_proportional",
        "inverse_vol",
    ] = "equal_weight"
    max_position_weight: float = Field(default=0.10, gt=0, le=1.0)
    max_sector_weight: float = Field(default=0.40, gt=0, le=1.0)
    do_not_buy: list[str] = Field(default_factory=list)


class StrategyConfig(BaseModel):
    strategy_id: str
    description: str = ""
    universe: UniverseConfig = UniverseConfig()
    regime_detection: RegimeDetectionConfig
    factor_weights: dict[str, FactorWeights]  # keyed by regime name
    # top-level max_positions is a convenience alias; portfolio_builder.max_positions takes precedence
    max_positions: int = Field(default=30, ge=1, le=500)
    min_score_percentile: float = Field(default=0.0, ge=0, le=1)
    min_non_null_factors: int = Field(default=3, ge=1, le=6)
    required_factors: list[str] = Field(default_factory=list)
    portfolio_builder: PortfolioBuilderConfig = Field(default_factory=PortfolioBuilderConfig)
    vetter: VetterConfig = Field(default_factory=VetterConfig)

    @model_validator(mode="after")
    def weights_match_regimes(self) -> StrategyConfig:
        regime_names = set(self.regime_detection.regimes.keys())
        weight_names = set(self.factor_weights.keys())
        missing = regime_names - weight_names
        if missing:
            raise ValueError(f"factor_weights missing entries for regimes: {missing}")
        return self
