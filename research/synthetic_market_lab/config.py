from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

GENERATOR_VERSION = "1.0.0"


class MacroConfig(BaseModel):
    model_config = ConfigDict(frozen=True)
    regime_persistence: float = Field(0.975, gt=0.8, lt=0.9999)
    state_reversion: float = Field(0.035, gt=0.0, lt=0.5)
    shock_decay: float = Field(0.965, gt=0.5, lt=0.9999)
    shock_daily_probability: float = Field(0.0025, ge=0.0, le=0.05)
    shock_scale: float = Field(1.0, gt=0.0, le=5.0)


class FactorConfig(BaseModel):
    model_config = ConfigDict(frozen=True)
    factor_reversion: float = Field(0.08, gt=0.0, lt=1.0)
    factor_noise: float = Field(0.0007, gt=0.0, lt=0.02)
    crowding_reversal_strength: float = Field(0.30, ge=0.0, le=2.0)


class CompanyConfig(BaseModel):
    model_config = ConfigDict(frozen=True)
    company_count: int = Field(200, ge=20, le=10000)
    initially_listed_fraction: float = Field(0.72, ge=0.1, le=1.0)
    latest_ipo_fraction_of_horizon: float = Field(0.70, gt=0.0, le=1.0)
    sectors: tuple[str, ...] = (
        "Industrials",
        "Technology",
        "Financials",
        "Health",
        "Consumer",
        "Energy",
        "Materials",
        "Utilities",
    )

    @model_validator(mode="after")
    def validate_sectors(self) -> "CompanyConfig":
        if len(self.sectors) < 4:
            raise ValueError("at least four sectors are required")
        if len(set(self.sectors)) != len(self.sectors):
            raise ValueError("sector names must be unique")
        return self


class DisclosureConfig(BaseModel):
    model_config = ConfigDict(frozen=True)
    filing_delay_min_sessions: int = Field(18, ge=1, le=120)
    filing_delay_max_sessions: int = Field(45, ge=2, le=180)
    missing_report_probability: float = Field(0.01, ge=0.0, le=0.25)
    restatement_probability: float = Field(0.055, ge=0.0, le=0.5)
    restatement_delay_min_sessions: int = Field(30, ge=1, le=500)
    restatement_delay_max_sessions: int = Field(180, ge=2, le=750)
    reporting_noise_std: float = Field(0.018, ge=0.0, le=0.25)

    @model_validator(mode="after")
    def validate_delays(self) -> "DisclosureConfig":
        if self.filing_delay_max_sessions < self.filing_delay_min_sessions:
            raise ValueError("filing delay max must be >= min")
        if self.restatement_delay_max_sessions < self.restatement_delay_min_sessions:
            raise ValueError("restatement delay max must be >= min")
        return self


class PriceConfig(BaseModel):
    model_config = ConfigDict(frozen=True)
    base_idio_vol_daily: float = Field(0.018, gt=0.001, le=0.2)
    vol_persistence: float = Field(0.94, ge=0.5, lt=1.0)
    vol_shock_weight: float = Field(0.10, ge=0.0, le=1.0)
    max_conditional_vol_daily: float = Field(0.18, gt=0.02, le=0.5)
    student_t_df: float = Field(5.0, gt=2.1, le=30.0)
    momentum_strength: float = Field(0.12, ge=0.0, le=0.8)
    mean_reversion_strength: float = Field(0.10, ge=0.0, le=0.8)
    min_price: float = Field(0.03, gt=0.0)
    max_daily_log_return: float = Field(0.95, gt=0.1, le=2.0)


class LiquidityConfig(BaseModel):
    model_config = ConfigDict(frozen=True)
    base_turnover_daily: float = Field(0.008, gt=0.0001, le=0.25)
    min_spread_bps: float = Field(2.0, gt=0.0, le=100.0)
    max_spread_bps: float = Field(1200.0, gt=10.0, le=10000.0)
    stress_spread_multiplier: float = Field(4.0, ge=1.0, le=20.0)


class ActionConfig(BaseModel):
    model_config = ConfigDict(frozen=True)
    annual_bankruptcy_base_probability: float = Field(0.010, ge=0.0, le=0.5)
    annual_acquisition_probability: float = Field(0.010, ge=0.0, le=0.5)
    annual_ticker_change_probability: float = Field(0.004, ge=0.0, le=0.5)
    annual_identifier_change_probability: float = Field(0.003, ge=0.0, le=0.5)
    annual_issuance_probability: float = Field(0.04, ge=0.0, le=0.8)
    annual_buyback_probability: float = Field(0.06, ge=0.0, le=0.8)
    split_price_threshold: float = Field(180.0, gt=1.0)
    reverse_split_price_threshold: float = Field(2.0, gt=0.01)
    split_cooldown_sessions: int = Field(252, ge=20, le=2520)
    delist_delay_sessions: int = Field(5, ge=0, le=30)
    dividend_quarterly_probability: float = Field(0.55, ge=0.0, le=1.0)
    dividend_payout_ratio: float = Field(0.22, ge=0.0, le=0.9)


class WorldConfig(BaseModel):
    model_config = ConfigDict(frozen=True)
    generator_version: Literal[GENERATOR_VERSION] = GENERATOR_VERSION
    seed: int = Field(20260907, ge=0, le=2**63 - 1)
    start_date: date = date(2000, 1, 3)
    years: int = Field(20, ge=1, le=100)
    sessions_per_year: int = Field(252, ge=200, le=366)
    macro: MacroConfig = MacroConfig()
    factors: FactorConfig = FactorConfig()
    companies: CompanyConfig = CompanyConfig()
    disclosures: DisclosureConfig = DisclosureConfig()
    prices: PriceConfig = PriceConfig()
    liquidity: LiquidityConfig = LiquidityConfig()
    actions: ActionConfig = ActionConfig()
    benchmark_public_ticker: str = "SYNMKT"
    benchmark_adapter_alias: str = "SPY"

    @property
    def session_count(self) -> int:
        return self.years * self.sessions_per_year

    def canonical_dict(self) -> dict:
        return self.model_dump(mode="json")

    def canonical_json(self) -> str:
        return json.dumps(self.canonical_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=True)

    def config_sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def world_id(self) -> str:
        payload = f"{self.generator_version}|{self.seed}|{self.canonical_json()}".encode("utf-8")
        return hashlib.sha256(payload).hexdigest()


def load_config(path: str) -> WorldConfig:
    with open(path, "r", encoding="utf-8") as handle:
        return WorldConfig.model_validate_json(handle.read())
