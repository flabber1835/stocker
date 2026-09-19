from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .config import FactorConfig
from .macro import MacroPath

FACTOR_NAMES = (
    "market",
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


@dataclass(frozen=True)
class FactorPath:
    values: np.ndarray


def generate_factors(macro: MacroPath, cfg: FactorConfig, rng: np.random.Generator) -> FactorPath:
    n = len(macro.regime_index)
    values = np.zeros((n, len(FACTOR_NAMES)), dtype=float)
    crowding = np.zeros(len(FACTOR_NAMES), dtype=float)

    for t in range(1, n):
        growth, inflation, policy, slope, credit_spread, liquidity, commodity, vol, productivity, risk = macro.state[t]
        target = np.array(
            [
                0.00018 + 0.0014 * growth + 0.00035 * risk - 0.00045 * credit_spread,
                0.00002 + 0.00030 * liquidity - 0.00030 * credit_spread,
                0.00003 + 0.00030 * inflation + 0.00020 * credit_spread - 0.00025 * productivity,
                0.00004 + 0.00045 * productivity + 0.00020 * risk - 0.00018 * policy,
                0.00005 + 0.00025 * growth - 0.00020 * credit_spread,
                0.00005 + 0.00018 * credit_spread + 0.00018 * vol - 0.00015 * risk,
                -0.00002 - 0.00030 * credit_spread - 0.00020 * policy + 0.00015 * risk,
                0.00006 + 0.00035 * risk - 0.00045 * vol,
                0.00001 - 0.00030 * policy + 0.00018 * slope,
                -0.00002 - 0.00045 * credit_spread + 0.00010 * risk,
                0.00002 + 0.00050 * commodity,
                0.00001 + 0.00035 * inflation - 0.00012 * policy,
                -0.00002 - 0.00035 * vol + 0.00015 * credit_spread,
                0.00002 + 0.00035 * liquidity - 0.00025 * vol,
            ],
            dtype=float,
        )
        crowding = 0.985 * crowding + 0.015 * np.sign(values[t - 1])
        reversal = -cfg.crowding_reversal_strength * crowding * np.maximum(np.abs(values[t - 1]) - 0.0012, 0.0)
        noise = rng.normal(0.0, cfg.factor_noise, len(FACTOR_NAMES))
        values[t] = (1.0 - cfg.factor_reversion) * values[t - 1] + cfg.factor_reversion * target + reversal + noise
        values[t] = np.clip(values[t], -0.025, 0.025)

    return FactorPath(values=values)
