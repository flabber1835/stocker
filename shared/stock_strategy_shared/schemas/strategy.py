from __future__ import annotations
from typing import Literal, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class FactorWeights(BaseModel):
    momentum: float = Field(ge=0, le=1)
    quality: float = Field(ge=0, le=1)
    value: float = Field(ge=0, le=1)
    growth: float = Field(ge=0, le=1)
    low_volatility: float = Field(ge=0, le=1)
    liquidity: float = Field(default=0.0, ge=0, le=1)  # optional, default 0
    issuance: float = Field(default=0.0, ge=0, le=1)   # net-share-issuance factor; optional, default 0
    # Speculative-style factors — all optional, default 0 so existing strategies are
    # unaffected (a 0 weight contributes nothing to the composite). Used by the
    # speculative_growth strategy to surface high-momentum, small-cap, high-vol,
    # breakout, accumulation names the core quality/value model screens out.
    small_cap: float = Field(default=0.0, ge=0, le=1)        # prefers smaller market cap
    volume_surge: float = Field(default=0.0, ge=0, le=1)     # recent vol vs baseline (accumulation)
    near_high: float = Field(default=0.0, ge=0, le=1)        # proximity to trailing high (breakout)
    high_volatility: float = Field(default=0.0, ge=0, le=1)  # inverse of low_volatility (prefers high vol)

    @model_validator(mode="after")
    def weights_sum_to_one(self) -> FactorWeights:
        total = (
            self.momentum + self.quality + self.value
            + self.growth + self.low_volatility + self.liquidity + self.issuance
            + self.small_cap + self.volume_surge + self.near_high + self.high_volatility
        )
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"Factor weights must sum to 1.0, got {total:.6f}")
        return self


class RegimeCondition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    """Conditions that define when a regime is active."""
    spy_above_slow_sma: bool
    vol_above_threshold: bool


class RegimeDetectionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

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
    model_config = ConfigDict(extra="forbid")

    source: str = "av_listing"
    min_price: float = 5.0
    min_avg_dollar_volume_20d: float = 20_000_000


class FactorEngineConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

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
    industry_neutral_factors: list[str] = Field(
        default_factory=lambda: ["value", "quality"],
        description="Factors percentile-ranked WITHIN the stock's own sector instead of "
                    "against the whole universe (Asness-Porter-Stevens within-industry pricing). "
                    "Restricted to value/quality/growth — momentum is partly industry momentum "
                    "(Moskowitz-Grinblatt), so neutralizing it deletes signal and is forbidden. "
                    "Defaults to [value, quality] (ON); set [] to disable (universe-wide ranking)."
    )
    min_sector_group_size: int = Field(
        default=10, ge=2, le=500,
        description="A sector must have at least this many tickers with a valid factor value to "
                    "be neutralized within; smaller sectors (and NULL-sector tickers) fall back "
                    "to universe-wide ranking so neutralization never reduces coverage."
    )
    quality_use_gross_profitability: bool = Field(
        default=False,
        description="When true, the quality factor's profitability leg is gross-profits-to-assets "
                    "(Novy-Marx) instead of ROE, keeping inverse-leverage as the safety leg. "
                    "Falls back to ROE when gross_profit/total_assets are absent. "
                    "False = legacy ROE + inverse-leverage composite."
    )
    momentum_method: str = Field(
        default="raw",
        description="How the momentum factor is computed before percentile ranking. "
                    "'raw' = plain 12-1 price return (Jegadeesh-Titman). "
                    "'risk_adjusted' = raw / formation-period volatility (Sharpe-like; "
                    "penalizes high-vol momentum, the names prone to momentum crashes). "
                    "'residual' = cumulative residual return after stripping the market "
                    "(equal-weight cross-sectional mean) — idiosyncratic momentum "
                    "(Blitz-Huij-Martens), far smaller crash tails. "
                    "'residual_riskadj' = residual / formation vol (both effects; the "
                    "cross-sectional analogue of vol-scaled/residual momentum). "
                    "Raw is the schema default for back-compat; quality_core_v1 opts into "
                    "residual_riskadj. Falls back to raw when there isn't enough history."
    )

    momentum_blend_windows: Optional[list[int]] = Field(
        default=None,
        description="When set to >1 long-window lengths (each sharing momentum_short_window "
                    "as the skip), the momentum factor is the rank-average of the chosen "
                    "momentum_method computed at each horizon — e.g. [252, 126] blends 12-1 "
                    "and 6-1 momentum so the factor reacts sooner to emerging trends while "
                    "still skipping the last month (reversal protection preserved). "
                    "None/one value = single-horizon (momentum_long_window)."
    )

    @field_validator("momentum_blend_windows")
    @classmethod
    def _valid_blend_windows(cls, v):
        if v is None:
            return v
        for w in v:
            if not (63 <= w <= 504):
                raise ValueError(f"momentum_blend_windows entries must be in [63, 504], got {w}")
        return v

    @field_validator("momentum_method")
    @classmethod
    def _valid_momentum_method(cls, v: str) -> str:
        allowed = {"raw", "risk_adjusted", "residual", "residual_riskadj"}
        if v not in allowed:
            raise ValueError(f"momentum_method must be one of {sorted(allowed)}, got {v!r}")
        return v

    @field_validator("industry_neutral_factors")
    @classmethod
    def _only_neutralizable_factors(cls, v: list[str]) -> list[str]:
        allowed = {"value", "quality", "growth"}
        bad = [f for f in v if f not in allowed]
        if bad:
            raise ValueError(
                f"industry_neutral_factors may only contain {sorted(allowed)} "
                f"(momentum/low_volatility/liquidity must never be sector-neutralized); got {bad}"
            )
        return v


class VetterConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

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
    model_config = ConfigDict(extra="forbid")

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


class ThemeOverlayConfig(BaseModel):
    """Optional thematic overlay for the portfolio-builder. DEFAULT OFF — when
    disabled the builder behaves exactly as before (no theme coupling).

    The overlay NEVER ranks by theme exposure — the deterministic quant rank always
    owns selection/sizing. The theme only acts as a membership FILTER or a bounded
    score TILT, fed from the standalone theme_exposures table (read-only). If the
    table is missing/empty the overlay degrades gracefully to no-theme behavior.

    Modes:
      tilt     — keep the full top-N candidate pool, multiply theme members'
                 composite score by (1 + tilt_lambda * exposure). Leans selection
                 toward AI names while they still compete on quant merit.
      restrict — candidate pool = theme universe members only (a dedicated sleeve),
                 still ranked/selected/weighted by quant rank. NOTE: a theme sleeve
                 is concentrated by design, so you will typically also relax
                 max_sector_weight / max_tickers_per_cluster / max_positions for it.
    """
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    theme: str = "ai_infra"
    mode: Literal["tilt", "restrict"] = "tilt"
    min_exposure: float = Field(
        default=0.35, ge=0.0, le=1.0,
        description="Membership threshold: a non-seed name joins the theme universe "
                    "at exposure >= this. Seeds are always members (mirrors /exposures).")
    tilt_lambda: float = Field(
        default=0.25, ge=0.0, le=2.0,
        description="tilt mode only: score multiplier is (1 + tilt_lambda * exposure). "
                    "0 = no tilt (members compete on raw quant). Higher = stronger lean.")


class PortfolioBuilderConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

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
    max_sector_weight: float = Field(
        default=0.30, gt=0, le=1.0,
        description=(
            "Hard cap on any single AV sector's share of the book, enforced as a "
            "SECOND, independent dimension alongside the correlation-cluster cap "
            "(max_cluster_weight). The cluster cap controls correlated micro-groups "
            "(e.g. tankers) but cannot see a whole sector spread across several "
            "clusters (e.g. energy = tankers + refiners + E&P), so the sector cap "
            "bounds that. Applied in both greedy_select (count proxy) and "
            "compute_weights (weight redistribution). Set to 1.0 to disable."
        ),
    )
    cluster_correlation_threshold: float = Field(
        default=0.70, gt=0, le=1.0,
        description=(
            "Absolute pairwise correlation at or above which two tickers are placed "
            "in the same correlation cluster (single-linkage). Clusters replace sector "
            "labels for concentration capping — provider sectors are unreliable "
            "(e.g. GOOG tagged Communication Services, gold miners split across sectors)."
        ),
    )
    max_cluster_weight: float = Field(
        default=0.15, gt=0, le=1.0,
        description=(
            "Maximum summed portfolio weight of any one correlation cluster. "
            "A 0.15 cap implies the portfolio spans >= 7 effectively-independent "
            "clusters when fully invested, preventing one correlated theme (e.g. golds) "
            "from dominating. Set to 1.0 to disable the cluster cap."
        ),
    )
    max_tickers_per_cluster: int | None = Field(
        default=None, ge=1,
        description=(
            "Hard cap on the NUMBER of holdings drawn from any one correlation "
            "cluster (count cap), complementary to max_cluster_weight (the weight/risk "
            "cap). Enforced during greedy selection: once a cluster has this many "
            "members selected, further candidates from it are skipped — whichever of "
            "the count cap and the weight cap binds first wins. Unlike the weight cap's "
            "count/target proxy, this is an absolute count independent of the weighting "
            "scheme and max_positions. None disables it; 1 = at most one name per "
            "cluster (max diversification). Singletons (no correlated peer) are "
            "unaffected — only multi-member clusters are thinned."
        ),
    )
    do_not_buy: list[str] = Field(default_factory=list)
    turnover_penalty: float = Field(
        default=0.0, ge=0.0, le=0.50,
        description=(
            "Fractional score discount applied to candidates NOT currently held. "
            "Default 0: the portfolio-builder is the SOURCE OF TRUTH and builds a "
            "fresh, holdings-agnostic target each day; churn-damping is owned by "
            "the delta engine's buffer-zone / confirmation-days hysteresis, not by "
            "biasing the target toward what is already held. Set > 0 to re-enable "
            "the old continuity bias (new positions score that fraction lower)."
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
    theme_overlay: ThemeOverlayConfig = Field(default_factory=ThemeOverlayConfig)

    @model_validator(mode="after")
    def position_weight_consistent_with_count(self) -> "PortfolioBuilderConfig":
        if self.max_positions > 0 and self.max_position_weight > 0:
            floor_weight = 1.0 / self.max_positions
            if self.max_position_weight > min(1.0, floor_weight * 3):
                raise ValueError(
                    f"max_position_weight {self.max_position_weight:.0%} is too high "
                    f"for max_positions={self.max_positions} "
                    f"(expected <= {floor_weight * 3:.0%})"
                )
        return self


class DeltaEngineConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entry_rank: int = Field(default=25, ge=1, le=500,
        description="Stocks ranked ≤ this for confirmation_days consecutive runs enter the portfolio.")
    exit_rank: int = Field(default=40, ge=1, le=500,
        description="Stocks ranked > this for confirmation_days consecutive runs exit the portfolio.")
    confirmation_days: int = Field(default=3, ge=1, le=21,
        description="Consecutive daily ranking runs required to confirm rank-based entry or exit.")
    orphan_confirmation_days: int = Field(default=2, ge=1, le=21,
        description=(
            "Consecutive portfolio BUILDS a held name must be absent from the target "
            "before it is orphan-exited (sold). Separate from confirmation_days so "
            "orphan disposal can be tightened without loosening the rank buffer. "
            "Default 2: flagged at_risk on build 1, sold on build 2."))
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
    regime_weighting_enabled: bool = Field(
        default=True,
        description="When True, factor weights are selected per detected regime "
                    "(factor_weights[regime]). When False, regime ROTATION is OFF: "
                    "the single static_factor_weights vector is used in ALL regimes. "
                    "Regime is still DETECTED (snapshots/dashboard) but no longer "
                    "changes the weights. Rationale: broad regime factor-rotation is "
                    "weakly supported out-of-sample and prone to overfitting on few "
                    "regime episodes (Asness; Cederburg et al.); a static multi-factor "
                    "vector is hard to beat. See docs/architecture.md.",
    )
    static_factor_weights: Optional[FactorWeights] = Field(
        default=None,
        description="Single factor-weight vector used in every regime when "
                    "regime_weighting_enabled is False. Required in that case.",
    )
    # top-level max_positions is a convenience alias; portfolio_builder.max_positions takes precedence
    max_positions: int = Field(default=30, ge=1, le=500)
    min_score_percentile: float = Field(default=0.0, ge=0, le=1)
    min_non_null_factors: int = Field(default=3, ge=1, le=11)
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
    def static_weights_present_when_regime_disabled(self) -> "StrategyConfig":
        if not self.regime_weighting_enabled and self.static_factor_weights is None:
            raise ValueError(
                "regime_weighting_enabled is False but static_factor_weights is not set "
                "— provide a single factor-weight vector to use in all regimes"
            )
        return self

    def effective_factor_weights(self, regime: str) -> FactorWeights:
        """The factor weights to SCORE with for `regime`.

        When regime_weighting_enabled is False, regime rotation is OFF and the
        single static_factor_weights vector is returned regardless of `regime`
        (regime is still detected for snapshots/dashboard, it just no longer
        changes the weights). Otherwise returns the per-regime vector. Single
        source of truth so the ranker and the audit/spot-check display agree.
        """
        if not self.regime_weighting_enabled:
            # Guaranteed non-None by static_weights_present_when_regime_disabled.
            return self.static_factor_weights  # type: ignore[return-value]
        return self.factor_weights[regime]

    @model_validator(mode="after")
    def liquidity_weight_consistent_with_required_factors(self) -> "StrategyConfig":
        if "liquidity" not in self.required_factors:
            return self
        # Check the weight vectors actually used for scoring: the static vector when
        # regime rotation is off, else every per-regime vector.
        if not self.regime_weighting_enabled:
            vectors = {"static": self.static_factor_weights} if self.static_factor_weights else {}
        else:
            vectors = self.factor_weights
        for regime, weights in vectors.items():
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
