from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, Field, model_validator


class FactorWeights(BaseModel):
    momentum: float = Field(ge=0, le=1)
    quality: float = Field(ge=0, le=1)
    value: float = Field(ge=0, le=1)
    growth: float = Field(ge=0, le=1)
    low_volatility: float = Field(ge=0, le=1)
    liquidity: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def weights_sum_to_one(self) -> FactorWeights:
        total = (
            self.momentum + self.quality + self.value
            + self.growth + self.low_volatility + self.liquidity
        )
        if abs(total - 1.0) > 0.01:
            raise ValueError(f"Factor weights must sum to 1.0, got {total:.4f}")
        return self


class RegimeWeights(BaseModel):
    bull: FactorWeights
    bear: FactorWeights
    neutral: FactorWeights


class UniverseConfig(BaseModel):
    source: Literal["etf_holdings"] = "etf_holdings"
    etf_ticker: str = "IWV"
    min_price: float = 5.0
    min_avg_dollar_volume_20d: float = 20_000_000


class StrategyConfig(BaseModel):
    strategy_id: str
    description: str = ""
    universe: UniverseConfig = UniverseConfig()
    factor_weights: RegimeWeights
    max_positions: int = Field(default=30, ge=1, le=500)
    min_score_percentile: float = Field(default=0.0, ge=0, le=1)
