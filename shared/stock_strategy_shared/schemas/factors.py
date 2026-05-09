from __future__ import annotations
from typing import Literal
from pydantic import BaseModel


RegimeType = Literal["bull", "bear", "neutral"]


class FactorScoreRow(BaseModel):
    ticker: str
    momentum: float | None
    quality: float | None
    value: float | None
    growth: float | None
    low_volatility: float | None
    liquidity: float | None
    composite_score: float | None = None


class RegimeSnapshot(BaseModel):
    regime: RegimeType
    spy_price: float | None
    spy_sma_50: float | None
    spy_sma_200: float | None
    spy_vs_sma200: float | None
