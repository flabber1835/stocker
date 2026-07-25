"""Terminal-wealth distributions via circular block bootstrap.

WHY THIS EXISTS. The promotion gate compared two configs on CAGR and a single
realised max drawdown — one number from one run through history. History ran
once, so that answers "what happened", not "what is likely". Two consequences:

  * the gate cannot separate BETTER from LUCKIER. A +1pp CAGR edge over ~100
    rebalances can come from two positions that happened to land well.
  * `max_drawdown` is one realised path. A config carrying a fat left tail that
    simply did not fire looks identical to a genuinely safe one — and the stated
    objective is long-run compounded wealth, whose enemy is exactly the drawdown
    arithmetic cannot recover from.

Resampling the realised returns many times gives a DISTRIBUTION of terminal
wealth. The median is the central outcome; the 5th percentile is the left tail
stated in the only unit that matters, money at the end.

HONEST LIMIT: a 2-year window at weekly rebalancing is ~100 observations, and a
bootstrap of 100 observations is itself noisy. This makes the uncertainty
VISIBLE and correctly signed; it does not manufacture information. Expect it to
make the gate harder to convince, not cleverer.

Design choices, each load-bearing:

  CIRCULAR blocks — the series wraps, so every observation has an equal chance
    of being drawn. A non-circular block bootstrap under-samples both ends
    (early points can only start a block, late points can only end one), which
    biases the tail exactly where it is being measured.
  BLOCKS, not IID draws — daily equity returns cluster (a volatile day follows a
    volatile day). IID resampling destroys that and understates the tail, which
    is the one thing this is for.
  PAIRED resampling — the benchmark is resampled with the SAME index draw, so
    "probability of beating SPY" preserves the joint co-movement instead of
    comparing two independently shuffled worlds.
  SEEDED — determinism is a system-wide contract; the same inputs must give the
    same numbers on every host and every rerun.

Pure: numpy only, no DB/env/clock.
"""
from __future__ import annotations

import math

import numpy as np

# ~1 trading month. Long enough to carry volatility clustering, short enough
# that a 2-year window still yields many distinct blocks.
DEFAULT_BLOCK_DAYS = 21
DEFAULT_PATHS = 2000
DEFAULT_SEED = 20260725

# A daily return of exactly -100% wipes the book out; clip fractionally above
# -1 so log1p stays finite and the path lands at ~0 rather than NaN.
_MIN_RETURN = -0.999999


def daily_returns(equity_rows: list[dict], value_key: str = "portfolio_value"
                  ) -> list[float]:
    """Equity curve -> simple daily returns. Rows must be chronological.

    Non-positive equity ends the series: once the book is worthless there is no
    meaningful further return, and dividing by it would produce inf/NaN that
    silently poisons every downstream statistic."""
    out: list[float] = []
    prev: float | None = None
    for row in equity_rows or []:
        try:
            v = float(row[value_key])
        except (KeyError, TypeError, ValueError):
            continue
        if prev is not None:
            if prev <= 0:
                break
            out.append(v / prev - 1.0)
        prev = v
    return out


def _block_index_matrix(n: int, block: int, n_paths: int,
                        rng: np.random.Generator) -> np.ndarray:
    """(n_paths, n) index matrix of CIRCULAR blocks.

    Each path is ceil(n/block) blocks of `block` consecutive indices, starting
    anywhere in [0, n) and wrapping modulo n, truncated back to exactly n so
    every resampled path has the same horizon as the original."""
    n_blocks = math.ceil(n / block)
    starts = rng.integers(0, n, size=(n_paths, n_blocks))
    offsets = np.arange(block)
    idx = (starts[:, :, None] + offsets[None, None, :]) % n
    return idx.reshape(n_paths, n_blocks * block)[:, :n]


def bootstrap_terminal_wealth(
    returns: list[float] | np.ndarray,
    *,
    starting_capital: float = 100_000.0,
    block_days: int = DEFAULT_BLOCK_DAYS,
    n_paths: int = DEFAULT_PATHS,
    seed: int = DEFAULT_SEED,
    benchmark_returns: list[float] | np.ndarray | None = None,
) -> dict | None:
    """Distribution of terminal wealth over resampled paths.

    Returns None when there is not enough data to say anything honest (fewer
    than 2 blocks' worth of observations) — a fabricated distribution over 5
    data points is worse than no distribution.

    `benchmark_returns`, when supplied and the same length, is resampled with
    the SAME draws so prob_beat_benchmark reflects joint behaviour."""
    r = np.asarray(list(returns), dtype=float)
    r = r[np.isfinite(r)]
    n = r.size
    block = max(1, int(block_days))
    if n < 2 * block or n_paths < 1:
        return None

    rng = np.random.default_rng(int(seed))
    idx = _block_index_matrix(n, block, int(n_paths), rng)

    # Log space: a product of hundreds of near-1 factors underflows long before
    # a sum of logs does, and the sum is what the percentiles are taken over.
    logs = np.log1p(np.clip(r, _MIN_RETURN, None))
    total = logs[idx].sum(axis=1)
    wealth = float(starting_capital) * np.exp(total)

    pct = {f"p{q}": float(np.percentile(wealth, q)) for q in (5, 25, 50, 75, 95)}
    out = {
        "starting_capital": float(starting_capital),
        "n_paths": int(n_paths),
        "n_observations": int(n),
        "block_days": block,
        "seed": int(seed),
        "median_terminal_wealth": round(pct["p50"], 2),
        "p5_terminal_wealth": round(pct["p5"], 2),
        "p25_terminal_wealth": round(pct["p25"], 2),
        "p75_terminal_wealth": round(pct["p75"], 2),
        "p95_terminal_wealth": round(pct["p95"], 2),
        # The objective, expressed as a multiple of what was put in.
        "median_multiple": round(pct["p50"] / float(starting_capital), 6),
        "p5_multiple": round(pct["p5"] / float(starting_capital), 6),
        "prob_loss": round(float((wealth < float(starting_capital)).mean()), 4),
    }

    if benchmark_returns is not None:
        b = np.asarray(list(benchmark_returns), dtype=float)
        if b.size == n and np.isfinite(b).all():
            blogs = np.log1p(np.clip(b, _MIN_RETURN, None))
            btotal = blogs[idx].sum(axis=1)      # SAME draws — paired
            out["prob_beat_benchmark"] = round(float((total > btotal).mean()), 4)
            out["median_excess_multiple"] = round(
                float(np.median(np.exp(total) - np.exp(btotal))), 6)
    return out


# The gate rule itself lives in shared/ — bt-engine PRODUCES the distribution,
# bt-scheduler CONSUMES it, and two copies of a promotion criterion is exactly
# the drift that has bitten this system before. Re-exported here so callers of
# this module get it without knowing where it lives.
from stock_strategy_shared.wealth import (  # noqa: E402,F401
    DEFAULT_TAIL_TOLERANCE, tail_is_acceptable)
