from __future__ import annotations

import numpy as np

from .companies import CompanyUniverse
from .config import LiquidityConfig, PriceConfig


def generate_bars(
    active_indices: np.ndarray,
    economic_base: np.ndarray,
    raw_base: np.ndarray,
    adj_scale: np.ndarray,
    prior_economic_return: np.ndarray,
    conditional_vol: np.ndarray,
    fundamental_signal: np.ndarray,
    health: np.ndarray,
    distress_probability: np.ndarray,
    companies: CompanyUniverse,
    shares: np.ndarray,
    factor_values: np.ndarray,
    sector_returns: np.ndarray,
    macro_state: np.ndarray,
    event_return_shock: np.ndarray,
    price_cfg: PriceConfig,
    liq_cfg: LiquidityConfig,
    rng: np.random.Generator,
) -> dict[str, np.ndarray]:
    idx = active_indices
    if len(idx) == 0:
        empty = np.array([], dtype=float)
        return {k: empty for k in ("open", "high", "low", "close", "adj_close", "volume", "dollar_volume", "spread_bps", "economic_return", "conditional_vol")}

    exposures = companies.exposures[idx]
    factor_component = np.sum(exposures * factor_values[None, :], axis=1)
    sector_component = 0.55 * sector_returns[companies.sector_index[idx]]
    macro_vol = float(macro_state[7])
    risk_appetite = float(macro_state[9])
    credit_spread = float(macro_state[4])
    liquidity_state = float(macro_state[5])

    momentum_sign = np.sign(factor_values[7])
    momentum_component = np.where(
        momentum_sign >= 0,
        price_cfg.momentum_strength * prior_economic_return[idx],
        -price_cfg.mean_reversion_strength * prior_economic_return[idx],
    )
    health_component = 0.00018 * health[idx] - 0.00045 * distress_probability[idx]
    fundamental_component = 0.004 * fundamental_signal[idx]
    drift = factor_component + sector_component + momentum_component + health_component + fundamental_component + event_return_shock[idx]

    base_vol = companies.base_volatility[idx]
    target_vol = base_vol * (1.0 + 0.9 * macro_vol + 1.2 * distress_probability[idx] + 0.35 * np.abs(exposures[:, 12]))
    innovation_target = target_vol + price_cfg.vol_shock_weight * np.abs(prior_economic_return[idx])
    conditional_vol[idx] = (
        price_cfg.vol_persistence * conditional_vol[idx]
        + (1.0 - price_cfg.vol_persistence) * innovation_target
    )
    conditional_vol[idx] = np.clip(conditional_vol[idx], 0.004, price_cfg.max_conditional_vol_daily)

    df = price_cfg.student_t_df
    t_scale = np.sqrt(df / (df - 2.0))
    idio = rng.standard_t(df, size=len(idx)) / t_scale * conditional_vol[idx]
    common_stress = rng.normal(0.0, 0.003 + 0.012 * macro_vol)
    log_return = np.clip(drift + idio + common_stress, -price_cfg.max_daily_log_return, price_cfg.max_daily_log_return)

    overnight = rng.normal(0.0, conditional_vol[idx] * 0.28)
    base_econ = economic_base[idx]
    open_econ = base_econ * np.exp(overnight)
    close_econ = base_econ * np.exp(log_return)
    intraday_range = np.abs(rng.standard_t(df, size=len(idx))) / t_scale * conditional_vol[idx] * 0.70
    high_econ = np.maximum(open_econ, close_econ) * np.exp(intraday_range)
    low_econ = np.minimum(open_econ, close_econ) * np.exp(-intraday_range)

    scale = adj_scale[idx]
    raw_open = np.maximum(price_cfg.min_price, open_econ / scale)
    raw_close = np.maximum(price_cfg.min_price, close_econ / scale)
    raw_high = np.maximum.reduce([raw_open, raw_close, high_econ / scale])
    raw_low = np.minimum.reduce([raw_open, raw_close, np.maximum(price_cfg.min_price, low_econ / scale)])

    shares_proxy = shares[idx]
    turnover = liq_cfg.base_turnover_daily * companies.base_liquidity[idx]
    stress = 1.0 + 1.4 * macro_vol + 1.0 * np.abs(log_return) + 0.7 * np.maximum(-liquidity_state, 0.0)
    volume = np.maximum(100.0, shares_proxy * turnover * stress * rng.lognormal(0.0, 0.35, size=len(idx)))
    dollar_volume = volume * raw_close

    size_penalty = 1.0 / np.maximum(companies.base_liquidity[idx], 0.05)
    spread = liq_cfg.min_spread_bps + 18.0 * size_penalty + 600.0 * conditional_vol[idx] + 350.0 * credit_spread
    spread *= 1.0 + (liq_cfg.stress_spread_multiplier - 1.0) * np.clip(macro_vol / 0.8, 0.0, 1.0)
    spread = np.clip(spread, liq_cfg.min_spread_bps, liq_cfg.max_spread_bps)

    economic_return = np.log(np.maximum(close_econ, 1e-12) / np.maximum(base_econ, 1e-12))
    return {
        "open": raw_open,
        "high": raw_high,
        "low": raw_low,
        "close": raw_close,
        "adj_close": close_econ,
        "volume": volume,
        "dollar_volume": dollar_volume,
        "spread_bps": spread,
        "economic_return": economic_return,
        "conditional_vol": conditional_vol[idx].copy(),
    }
