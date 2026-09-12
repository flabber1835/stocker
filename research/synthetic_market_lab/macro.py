from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .config import MacroConfig

REGIMES = (
    "expansion",
    "recession",
    "recovery",
    "inflationary_stagnation",
    "disinflation",
    "deflation",
    "tight_money",
    "easy_money",
    "calm_low_vol",
    "high_vol_sideways",
)

SHOCK_TYPES = (
    "credit",
    "energy",
    "supply",
    "geopolitical",
    "liquidity",
    "productivity",
    "bubble",
)

# growth, inflation, policy_rate, yield_slope, credit_spread, liquidity,
# commodity_impulse, volatility, productivity, risk_appetite
REGIME_TARGETS = np.array(
    [
        [0.035, 0.022, 0.030, 0.012, 0.012, 0.85, 0.00, 0.13, 0.015, 0.70],
        [-0.030, 0.012, 0.018, -0.005, 0.045, 0.30, -0.01, 0.38, -0.010, -0.55],
        [0.020, 0.015, 0.012, 0.020, 0.025, 0.60, 0.00, 0.23, 0.010, 0.30],
        [-0.010, 0.055, 0.060, -0.010, 0.035, 0.38, 0.03, 0.32, -0.005, -0.30],
        [0.018, 0.015, 0.028, 0.008, 0.018, 0.68, -0.01, 0.18, 0.008, 0.45],
        [-0.020, -0.010, 0.005, 0.015, 0.035, 0.42, -0.03, 0.30, -0.015, -0.45],
        [0.010, 0.040, 0.070, -0.018, 0.030, 0.35, 0.00, 0.28, 0.005, -0.20],
        [0.015, 0.018, 0.005, 0.025, 0.020, 0.78, 0.00, 0.16, 0.005, 0.55],
        [0.025, 0.020, 0.025, 0.010, 0.010, 0.92, 0.00, 0.08, 0.010, 0.80],
        [0.000, 0.025, 0.032, 0.000, 0.038, 0.25, 0.00, 0.48, 0.000, -0.60],
    ],
    dtype=float,
)


@dataclass(frozen=True)
class MacroPath:
    regime_index: np.ndarray
    state: np.ndarray
    shocks: np.ndarray
    shock_events: tuple[dict[str, object], ...]

    @property
    def regime(self) -> list[str]:
        return [REGIMES[int(i)] for i in self.regime_index]


def generate_macro(session_count: int, cfg: MacroConfig, rng: np.random.Generator) -> MacroPath:
    regimes = np.zeros(session_count, dtype=np.int16)
    state = np.zeros((session_count, REGIME_TARGETS.shape[1]), dtype=float)
    shocks = np.zeros((session_count, len(SHOCK_TYPES)), dtype=float)
    shock_events: list[dict[str, object]] = []

    regimes[0] = 0
    state[0] = REGIME_TARGETS[0]
    shock_state = np.zeros(len(SHOCK_TYPES), dtype=float)

    transition_bias = np.array([1.2, 1.0, 1.1, 0.7, 0.8, 0.5, 0.8, 0.9, 1.0, 0.7], dtype=float)
    transition_bias /= transition_bias.sum()

    signed = np.array([1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0], dtype=float)
    for t in range(1, session_count):
        prior_regime = int(regimes[t - 1])
        if rng.random() < cfg.regime_persistence:
            regimes[t] = prior_regime
        else:
            weights = transition_bias.copy()
            weights[prior_regime] *= 0.2
            weights /= weights.sum()
            regimes[t] = int(rng.choice(len(REGIMES), p=weights))

        shock_state *= cfg.shock_decay
        arrivals = rng.random(len(SHOCK_TYPES)) < cfg.shock_daily_probability
        if arrivals.any():
            magnitudes = rng.gamma(shape=2.0, scale=0.55, size=len(SHOCK_TYPES)) * cfg.shock_scale
            # Energy and bubble shocks can be booms or crashes; productivity can be positive or negative.
            signs = signed.copy()
            for j in (1, 5, 6):
                signs[j] = 1.0 if rng.random() < 0.65 else -1.0
            additions = arrivals * magnitudes * signs
            shock_state += additions
            for j in np.flatnonzero(arrivals):
                shock_events.append(
                    {
                        "session": t,
                        "shock_id": f"K{len(shock_events)+1:06d}",
                        "shock_type": SHOCK_TYPES[int(j)],
                        "intensity": float(additions[j]),
                        "source": "structural_poisson",
                        "affected_scope": "macro",
                    }
                )
        shocks[t] = shock_state

        target = REGIME_TARGETS[int(regimes[t])].copy()
        credit, energy, supply, geopolitical, liquidity, productivity, bubble = shock_state
        target[0] += -0.020 * credit - 0.012 * supply - 0.008 * geopolitical + 0.022 * productivity + 0.010 * bubble
        target[1] += 0.018 * energy + 0.016 * supply - 0.010 * productivity
        target[2] += 0.025 * max(target[1] - 0.02, -0.02)
        target[3] += -0.010 * credit + 0.006 * productivity
        target[4] += 0.030 * credit + 0.020 * liquidity + 0.010 * geopolitical
        target[5] += -0.35 * liquidity - 0.18 * credit + 0.08 * bubble
        target[6] += 0.045 * energy
        target[7] += 0.18 * abs(credit) + 0.16 * abs(liquidity) + 0.10 * abs(geopolitical) + 0.08 * abs(energy)
        target[8] += 0.030 * productivity
        target[9] += -0.35 * credit - 0.25 * liquidity - 0.12 * geopolitical + 0.25 * bubble + 0.18 * productivity

        noise_scale = np.array([0.0025, 0.0018, 0.0015, 0.0020, 0.0025, 0.030, 0.015, 0.018, 0.0020, 0.045])
        innovation = rng.normal(0.0, noise_scale)
        state[t] = state[t - 1] + cfg.state_reversion * (target - state[t - 1]) + innovation
        state[t, 2] = max(-0.01, state[t, 2])
        state[t, 4] = max(0.001, state[t, 4])
        state[t, 5] = float(np.clip(state[t, 5], -0.5, 1.5))
        state[t, 7] = float(np.clip(state[t, 7], 0.04, 1.5))
        state[t, 9] = float(np.clip(state[t, 9], -1.5, 1.5))

    return MacroPath(regime_index=regimes, state=state, shocks=shocks, shock_events=tuple(shock_events))
