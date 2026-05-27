from __future__ import annotations
from typing import Literal, Optional
from pydantic import BaseModel, ConfigDict, Field, model_validator


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
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"Factor weights must sum to 1.0, got {total:.6f}")
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
    source: str = "av_listing"
    min_price: float = 5.0
    min_avg_dollar_volume_20d: float = 20_000_000


class FactorEngineConfig(BaseModel):
    """Parameters governing how factor scores are computed.

    Changing these values produces a different set of factor scores and therefore
    a different ranking and portfolio — they are investment-thesis parameters, not
    implementation details.
    """
    zscore_clip: float = Field(
        default=2.5, gt=0, le=10,
        description="Hard clip applied after cross-sectional z-scoring. Larger = more outlier exposure."
    )
    momentum_short_window: int = Field(
        default=21, ge=5, le=63,
        description="Days used as the recent-price reference (skip-last-month)."
    )
    momentum_long_window: int = Field(
        default=252, ge=126, le=504,
        description="Days used as the base-price reference for the momentum return."
    )
    volatility_window: int = Field(
        default=252, ge=63, le=504,
        description="Trading days of log-return history used to compute realized vol for low_volatility factor."
    )
    liquidity_window: int = Field(
        default=20, ge=5, le=63,
        description="Trading days over which average dollar volume is computed for the liquidity factor."
    )
    pe_pb_cap: float = Field(
        default=50.0, gt=0, le=500,
        description="PE and PB ratios are capped at this value before computing yields. "
                    "Lower = more deep-value exposure; higher = more growth tolerance."
    )
    spy_price_lookback_days: int = Field(
        default=600, ge=300, le=1500,
        description="Calendar days of SPY price history loaded for regime detection. "
                    "Must exceed slow_sma + confirmation_days with comfortable margin."
    )


class VetterConfig(BaseModel):
    enabled: bool = Field(
        default=True,
        description="Set false to skip LLM vetting entirely for this strategy."
    )
    candidate_count: int = Field(default=50, ge=5, le=200)
    risk_horizon_days: int = Field(
        default=90, ge=1, le=365,
        description="Risk assessment horizon passed to the LLM. Events beyond this window are treated as "
                    "background noise. Holding periods are variable (weeks to months) under the buffer-zone model."
    )
    system_prompt_file: Optional[str] = Field(
        default=None,
        description="Path to a custom system prompt file for the LLM vetter. "
                    "Supports placeholders: {entry_rank}, {exit_rank}, {confirmation_days}, "
                    "{risk_horizon_days}, {exclude_clause}. If None, the built-in prompt is used."
    )
    max_searches_per_ticker: int = Field(
        default=3, ge=1, le=10,
        description="Maximum agentic web searches the LLM may make per ticker."
    )
    news_lookback_days: int = Field(
        default=7, ge=1, le=30,
        description="How far back to fetch Alpha Vantage news sentiment."
    )
    max_articles_per_ticker: int = Field(
        default=4, ge=1, le=20,
        description="Maximum AV news articles loaded per ticker."
    )
    earnings_horizon_days: int = Field(
        default=90, ge=14, le=180,
        description="Fetch upcoming earnings if they fall within this many days."
    )
    strictness: Literal["strict", "moderate", "permissive"] = Field(
        default="moderate",
        description=(
            "strict: exclude on any material concern even if uncertain. "
            "moderate: exclude only on CLEAR and SPECIFIC new unpriced risk. "
            "permissive: exclude only on imminent binary events."
        )
    )

class IntradayConfig(BaseModel):
    """Intraday monitoring behaviour.

    The intraday-monitor service is not yet built. This section is here so
    strategies can declare their intended intraday rules now and the service
    will read them when implemented.
    """
    enabled: bool = False
    benchmark_ticker: str = "SPY"
    # Winner-trimming: trim partial position near close after a strong day
    trim_winners_enabled: bool = False
    trim_winner_threshold_pct: float = Field(
        default=10.0, gt=0,
        description="Intraday gain % that triggers a trim (e.g. 10.0 = stock up 10% today)."
    )
    trim_winner_partial_pct: float = Field(
        default=25.0, gt=0, le=100,
        description="Fraction of position to sell when trimming (e.g. 25.0 = sell 25%)."
    )
    trim_time_window_minutes_before_close: int = Field(
        default=60, ge=5,
        description="Only consider trimming within this many minutes before market close."
    )
    # Buy delays: don't buy a stock that spiked hard pre/intraday
    delay_buys_after_spike_enabled: bool = False
    delay_buy_spike_threshold_pct: float = Field(
        default=15.0, gt=0,
        description="Skip a planned buy if the stock is already up this % on the entry day."
    )
    # Risk event response: cut vs reduce vs hold after a risk signal fires
    risk_event_action: Literal["cut", "reduce", "hold"] = "reduce"


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
    max_sector_weight: float = Field(default=0.30, gt=0, le=1.0)
    do_not_buy: list[str] = Field(default_factory=list)
    turnover_penalty: float = Field(
        default=0.05, ge=0.0, le=0.50,
        description=(
            "Fractional score discount applied to candidates NOT in the current portfolio. "
            "E.g. 0.05 = new positions score 5% lower than continuity holdings, all else equal. "
            "Reduces unnecessary churn on regime transitions. Set 0 to disable."
        ),
    )
    cash_reserve: float = Field(
        default=0.0, ge=0.0, lt=1.0,
        description=(
            "Fraction of account value to keep uninvested. "
            "E.g. 0.05 = weights scaled so total notional = 95% of account value. "
            "Prevents buying-power exhaustion when broker reserves exceed 100% for pending OPG orders."
        ),
    )


class DeltaEngineConfig(BaseModel):
    entry_rank: int = Field(default=25, ge=1, le=500,
        description="Stocks ranked ≤ this for confirmation_days consecutive runs enter the portfolio.")
    exit_rank: int = Field(default=40, ge=1, le=500,
        description="Stocks ranked > this for confirmation_days consecutive runs exit the portfolio.")
    confirmation_days: int = Field(default=3, ge=1, le=21,
        description="Consecutive daily ranking runs required to confirm entry or exit.")
    max_positions: int = Field(default=30, ge=1, le=100,
        description="Maximum portfolio size. New entries blocked when at capacity unless a simultaneous exit creates room.")
    rebalance_drift_threshold: float = Field(
        default=0.02, gt=0, le=0.5,
        description=(
            "Absolute weight drift that triggers a BUY-ADD or SELL-TRIM intent. "
            "E.g. 0.02 = propose a trim/add when actual weight deviates >2pp from target. "
            "Drift rebalance is skipped when no successful alpaca-sync exists."
        )
    )

    @model_validator(mode="after")
    def exit_rank_exceeds_entry_rank(self) -> "DeltaEngineConfig":
        if self.exit_rank <= self.entry_rank:
            raise ValueError(
                f"exit_rank ({self.exit_rank}) must be greater than entry_rank ({self.entry_rank}) to create a buffer zone"
            )
        return self


class StrategyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    strategy_id: str
    description: str = ""
    universe: UniverseConfig = Field(default_factory=UniverseConfig)
    factor_engine: FactorEngineConfig = Field(default_factory=FactorEngineConfig)
    regime_detection: RegimeDetectionConfig
    factor_weights: dict[str, FactorWeights]  # keyed by regime name
    # top-level max_positions is a convenience alias; portfolio_builder.max_positions takes precedence
    max_positions: int = Field(default=30, ge=1, le=500)
    min_score_percentile: float = Field(default=0.0, ge=0, le=1)
    min_non_null_factors: int = Field(default=3, ge=1, le=6)
    required_factors: list[str] = Field(default_factory=list)
    deduplicate_share_classes: bool = Field(
        default=True,
        description="When True, keep only the highest-ranked ticker per company name, "
                    "removing duplicate share classes (e.g. GOOG vs GOOGL) from rankings.",
    )
    portfolio_builder: PortfolioBuilderConfig = Field(default_factory=PortfolioBuilderConfig)
    vetter: VetterConfig = Field(default_factory=VetterConfig)
    intraday: IntradayConfig = Field(default_factory=IntradayConfig)
    delta_engine: DeltaEngineConfig = Field(default_factory=DeltaEngineConfig)

    @model_validator(mode="after")
    def sync_max_positions(self) -> "StrategyConfig":
        pb_field_default = PortfolioBuilderConfig.model_fields["max_positions"].default
        if (self.portfolio_builder.max_positions == pb_field_default
                and self.max_positions != pb_field_default):
            self.portfolio_builder.max_positions = self.max_positions
        return self

    @model_validator(mode="after")
    def weights_match_regimes(self) -> StrategyConfig:
        regime_names = set(self.regime_detection.regimes.keys())
        weight_names = set(self.factor_weights.keys())
        missing = regime_names - weight_names
        extra = weight_names - regime_names
        errors = []
        if missing:
            errors.append(f"factor_weights missing entries for regimes: {missing}")
        if extra:
            errors.append(f"factor_weights has entries for unknown regimes: {extra}")
        if errors:
            raise ValueError("; ".join(errors))
        return self

    @model_validator(mode="after")
    def liquidity_weight_consistent_with_required_factors(self) -> "StrategyConfig":
        if "liquidity" not in self.required_factors:
            return self
        for regime, weights in self.factor_weights.items():
            if weights.liquidity == 0.0:
                raise ValueError(
                    f"required_factors includes 'liquidity' but regime '{regime}' has liquidity weight 0.0 "
                    f"— either add a liquidity weight or remove it from required_factors"
                )
        return self

    @model_validator(mode="after")
    def vetter_candidate_count_covers_portfolio(self) -> "StrategyConfig":
        if not self.vetter.enabled:
            return self
        n = self.portfolio_builder.max_positions
        c = self.vetter.candidate_count
        if n > c:
            raise ValueError(
                f"portfolio_builder.max_positions ({n}) exceeds vetter.candidate_count ({c}) "
                f"— vetter will not have enough candidates to fill the portfolio"
            )
        return self
