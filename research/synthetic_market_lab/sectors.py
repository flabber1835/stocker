from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class SectorPath:
    names: tuple[str, ...]
    returns: np.ndarray
    macro_loadings: np.ndarray


def generate_sectors(
    sector_names: tuple[str, ...],
    factor_values: np.ndarray,
    macro_state: np.ndarray,
    rng: np.random.Generator,
) -> SectorPath:
    k = len(sector_names)
    n = factor_values.shape[0]
    # growth, inflation, rates, slope, credit, liquidity, commodity, vol, productivity, risk appetite
    loadings = rng.normal(0.0, 0.28, size=(k, 10))
    names_lower = [s.lower() for s in sector_names]
    for i, name in enumerate(names_lower):
        if "energy" in name:
            loadings[i, 6] += 1.4
            loadings[i, 1] += 0.5
        if "financial" in name:
            loadings[i, 2] += 0.7
            loadings[i, 3] += 0.6
            loadings[i, 4] -= 0.8
        if "technology" in name:
            loadings[i, 2] -= 0.8
            loadings[i, 8] += 0.9
            loadings[i, 9] += 0.4
        if "utility" in name:
            loadings[i, 2] -= 0.9
            loadings[i, 1] -= 0.4
        if "industrial" in name or "material" in name:
            loadings[i, 0] += 0.8
            loadings[i, 6] += 0.4
        if "health" in name:
            loadings[i, 0] -= 0.3
            loadings[i, 8] += 0.3
        if "consumer" in name:
            loadings[i, 0] += 0.5
            loadings[i, 9] += 0.3

    returns = np.zeros((n, k), dtype=float)
    persistent = np.zeros(k, dtype=float)
    for t in range(n):
        vol_state = float(macro_state[t, 7])
        common = 0.65 * float(factor_values[t, 0])
        macro_impulse = loadings @ macro_state[t]
        macro_component = 0.00045 * macro_impulse
        # Stress raises common correlation by shrinking sector-specific noise relative to common movement.
        idio_scale = max(0.0012, 0.0032 * (1.0 - min(vol_state, 0.8) * 0.45))
        sector_noise = rng.normal(0.0, idio_scale, size=k)
        persistent = 0.72 * persistent + 0.28 * sector_noise
        stress_common = rng.normal(0.0, 0.001 + 0.006 * vol_state)
        returns[t] = np.clip(common + macro_component + persistent + stress_common, -0.12, 0.12)
    return SectorPath(names=sector_names, returns=returns, macro_loadings=loadings)
