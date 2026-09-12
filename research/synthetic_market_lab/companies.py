from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .config import CompanyConfig


@dataclass(frozen=True)
class CompanyUniverse:
    company_id: np.ndarray
    sector_index: np.ndarray
    sector: np.ndarray
    industry: np.ndarray
    listing_session: np.ndarray
    initial_age_days: np.ndarray
    fiscal_quarter_offset: np.ndarray
    base_quality: np.ndarray
    base_growth: np.ndarray
    base_margin: np.ndarray
    cyclicality: np.ndarray
    base_liquidity: np.ndarray
    base_volatility: np.ndarray
    exposures: np.ndarray
    initial_price: np.ndarray
    initial_shares: np.ndarray
    initial_revenue: np.ndarray
    initial_assets: np.ndarray
    initial_debt: np.ndarray
    initial_cash: np.ndarray


EXPOSURE_NAMES = (
    "market_beta",
    "size",
    "value",
    "growth",
    "profitability",
    "quality",
    "leverage",
    "momentum",
    "duration",
    "credit",
    "commodity",
    "inflation",
    "volatility",
    "liquidity",
)


def generate_companies(cfg: CompanyConfig, session_count: int, rng: np.random.Generator) -> CompanyUniverse:
    n = cfg.company_count
    sector_count = len(cfg.sectors)
    company_id = np.array([f"C{i+1:06d}" for i in range(n)], dtype=object)
    sector_index = rng.integers(0, sector_count, size=n, endpoint=False)
    sector = np.array([cfg.sectors[int(i)] for i in sector_index], dtype=object)
    industry = np.array([f"{s[:4].upper()}-{int(i)%3+1}" for s, i in zip(sector, np.arange(n))], dtype=object)

    listed_now = rng.random(n) < cfg.initially_listed_fraction
    latest = max(1, int(session_count * cfg.latest_ipo_fraction_of_horizon))
    listing_session = np.where(listed_now, 0, rng.integers(1, latest + 1, size=n))
    initial_age_days = rng.integers(180, 25 * 365, size=n)
    fiscal_quarter_offset = rng.integers(0, 63, size=n, endpoint=False)

    base_quality = np.clip(rng.normal(0.0, 0.85, size=n), -2.5, 2.5)
    base_growth = np.clip(rng.normal(0.08, 0.11, size=n) + 0.035 * (sector_index == 1), -0.20, 0.55)
    base_margin = np.clip(rng.normal(0.11, 0.08, size=n) + 0.025 * base_quality, -0.10, 0.40)
    cyclicality = np.clip(rng.normal(0.8, 0.45, size=n), 0.0, 2.0)
    base_liquidity = np.clip(rng.lognormal(mean=-0.15, sigma=0.75, size=n), 0.08, 8.0)
    base_volatility = np.clip(rng.lognormal(mean=-3.8, sigma=0.35, size=n), 0.008, 0.08)

    exposures = np.zeros((n, len(EXPOSURE_NAMES)), dtype=float)
    exposures[:, 0] = np.clip(rng.normal(1.0, 0.28, size=n), 0.15, 2.0)
    exposures[:, 1] = rng.normal(0.0, 0.85, size=n)
    exposures[:, 2] = rng.normal(0.0, 0.75, size=n) - 0.25 * base_growth
    exposures[:, 3] = rng.normal(0.0, 0.75, size=n) + 0.70 * base_growth
    exposures[:, 4] = rng.normal(0.0, 0.55, size=n) + 0.45 * base_margin
    exposures[:, 5] = rng.normal(0.0, 0.55, size=n) + 0.55 * base_quality
    exposures[:, 6] = rng.normal(0.0, 0.65, size=n) - 0.35 * base_quality
    exposures[:, 7] = rng.normal(0.0, 0.70, size=n)
    exposures[:, 8] = rng.normal(0.0, 0.65, size=n) + 0.45 * base_growth
    exposures[:, 9] = np.clip(rng.normal(0.5, 0.4, size=n) - 0.20 * base_quality, -0.5, 2.0)
    exposures[:, 10] = rng.normal(0.0, 0.30, size=n) + 1.2 * (sector_index == 5) + 0.55 * (sector_index == 6)
    exposures[:, 11] = rng.normal(0.0, 0.55, size=n) + 0.6 * (sector_index == 5) - 0.4 * (sector_index == 7)
    exposures[:, 12] = np.clip(rng.normal(0.6, 0.4, size=n), -0.2, 2.0)
    exposures[:, 13] = rng.normal(0.0, 0.60, size=n) + 0.45 * np.log(base_liquidity)

    initial_price = np.clip(rng.lognormal(mean=3.25, sigma=0.75, size=n), 1.5, 220.0)
    initial_shares = np.clip(rng.lognormal(mean=np.log(55_000_000), sigma=1.0, size=n), 2_000_000, 1_200_000_000)
    market_cap = initial_price * initial_shares
    initial_revenue = market_cap * np.clip(rng.lognormal(mean=-0.05, sigma=0.55, size=n), 0.15, 3.5)
    initial_assets = initial_revenue * np.clip(rng.lognormal(mean=0.18, sigma=0.45, size=n), 0.5, 5.0)
    leverage_ratio = np.clip(0.32 - 0.06 * base_quality + rng.normal(0, 0.12, size=n), 0.03, 0.78)
    initial_debt = initial_assets * leverage_ratio
    initial_cash = initial_assets * np.clip(0.12 + 0.035 * base_quality + rng.normal(0, 0.05, size=n), 0.01, 0.45)

    return CompanyUniverse(
        company_id=company_id,
        sector_index=sector_index,
        sector=sector,
        industry=industry,
        listing_session=listing_session.astype(int),
        initial_age_days=initial_age_days.astype(int),
        fiscal_quarter_offset=fiscal_quarter_offset.astype(int),
        base_quality=base_quality,
        base_growth=base_growth,
        base_margin=base_margin,
        cyclicality=cyclicality,
        base_liquidity=base_liquidity,
        base_volatility=base_volatility,
        exposures=exposures,
        initial_price=initial_price,
        initial_shares=initial_shares,
        initial_revenue=initial_revenue,
        initial_assets=initial_assets,
        initial_debt=initial_debt,
        initial_cash=initial_cash,
    )
