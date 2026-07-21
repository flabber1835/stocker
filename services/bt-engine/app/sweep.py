"""Phase 5 — deterministic walk-forward parameter sweep (NO AI in the loop).

Plan decisions (docs/backtester-v2-plan.md "Phase 5", DECISION LOCKED):
  - The optimizer is a DETERMINISTIC grid sweep, never an LLM picking numbers:
    same grid + same data ⇒ the identical leaderboard, reproducibly.
  - WALK-FORWARD is mandatory: every config runs on the TUNE window and is
    SCORED on the VALIDATE window it was never selected on; the leaderboard
    ranks by out-of-sample Sharpe with the in-vs-out gap alongside so a config
    that only wins in-sample is visibly overfit.
  - PROTECTED_PATHS (falling-knife etc.) are NOT enforced here — this is the
    wind tunnel, human-launched offline research, and the plan's own example
    grids sweep drawdown thresholds. Protection applies to the LIVE tuner path.

Implementation decisions (recorded in the plan doc):
  - Lives inside bt-engine (no separate service): it drives run_simulation
    in-process. One shared data load serves both windows — safe because the sim
    is truncation-proven to never read past its own end date.
  - Sweep legs write bt_sweep_results only; bt_runs stays the interactive-run
    history.

This module is PURE (grid math + per-config execution given frames); main.py
owns the DB and the background job.
"""
from __future__ import annotations

import itertools
import random
from dataclasses import dataclass
from datetime import date
from typing import Any

from stock_strategy_shared.schemas.strategy import StrategyConfig

from app.sim import SimParams, run_simulation


def enumerate_grid(grid: dict[str, list], max_configs: int = 200,
                   sample_seed: int = 0) -> list[dict[str, Any]]:
    """Cartesian product of {dotted.path: [values]} → list of config diffs, in a
    DETERMINISTIC order (sorted keys, positional product). If the full grid
    exceeds max_configs, a seeded random sample keeps the run bounded while
    remaining reproducible (same grid + same seed ⇒ same subset)."""
    if not grid:
        return [{}]
    keys = sorted(grid)
    combos = list(itertools.product(*(grid[k] for k in keys)))
    diffs = [dict(zip(keys, combo)) for combo in combos]
    if len(diffs) > max_configs:
        rng = random.Random(sample_seed)
        diffs = rng.sample(diffs, max_configs)
        diffs.sort(key=lambda d: tuple(str(d[k]) for k in keys))  # stable order
    return diffs


def merge_extra_configs(diffs: list[dict], extras: list[dict] | None,
                        base: dict) -> tuple[list[dict], list]:
    """Experiment queue (Phase 6b): append evaluator-proposed single-diff
    configs AFTER grid enumeration — never cross-multiplied, so proposals can't
    explode the config count. Drops (never fatal — one bad proposal must not
    kill the standing sweep): non-dicts, empties, duplicates of a grid diff or
    an earlier extra, and diffs that fail StrategyConfig validation against the
    base. Returns (merged_diffs, dropped) — dropped is the LIST of rejected
    extras verbatim, so the caller (bt-scheduler) can mark exactly those
    proposals 'invalid' instead of falsely 'testing' (audit F2)."""
    merged = list(diffs)
    dropped: list = []
    for extra in extras or []:
        if not isinstance(extra, dict) or not extra or extra in merged:
            dropped.append(extra)
            continue
        _validated, err = apply_diff(base, extra)
        if err is not None:
            dropped.append(extra)
            continue
        merged.append(extra)
    return merged, dropped


def apply_diff(base: dict, diff: dict[str, Any]) -> tuple[dict | None, str | None]:
    """Apply {dotted.path: value} onto a base config dict and validate through
    StrategyConfig. Returns (validated_dict, None) or (None, error)."""
    import copy
    cfg = copy.deepcopy(base)
    for path, value in (diff or {}).items():
        parts = [p for p in str(path).split(".") if p]
        if not parts:
            return None, f"invalid config path: {path!r}"
        node = cfg
        for p in parts[:-1]:
            if not isinstance(node, dict):
                return None, f"config path {path!r} traverses a non-object at {p!r}"
            node = node.setdefault(p, {})
        if not isinstance(node, dict):
            return None, f"config path {path!r} traverses a non-object"
        node[parts[-1]] = value
    try:
        validated = StrategyConfig(**cfg)
    except Exception as exc:  # noqa: BLE001 — schema error text is the useful output
        return None, f"invalid config: {exc}"
    return validated.model_dump(mode="json"), None


@dataclass
class SweepWindows:
    tune_start: date
    tune_end: date
    validate_start: date
    validate_end: date

    def validate(self) -> str | None:
        if self.tune_end <= self.tune_start:
            return "tune_end must be after tune_start"
        if self.validate_end <= self.validate_start:
            return "validate_end must be after validate_start"
        if self.validate_start < self.tune_end:
            return ("validate window must start at/after tune_end — walk-forward "
                    "out-of-sample scoring is mandatory (no overlap)")
        return None


def run_config_both_windows(prices, fundamentals, sector_map, base_config: dict,
                            diff: dict, windows: SweepWindows,
                            sim_kwargs: dict, factor_cache=None) -> dict:
    """Run ONE config over tune + validate windows. Returns a result-row dict
    (never raises — an invalid/failed config becomes an error row so one bad
    grid point can't kill the sweep)."""
    cfg_dict, err = apply_diff(base_config, diff)
    if err:
        return {"config_diff": diff, "error_message": err}
    cfg = StrategyConfig(**cfg_dict)

    def _one(start: date, end: date) -> dict:
        params = SimParams(start=start, end=end, **sim_kwargs)
        return run_simulation(prices, fundamentals, sector_map, cfg, params,
                              factor_cache=factor_cache).summary

    try:
        in_sample = _one(windows.tune_start, windows.tune_end)
        out_sample = _one(windows.validate_start, windows.validate_end)
    except Exception as exc:  # noqa: BLE001
        return {"config_diff": diff, "error_message": f"sim failed: {str(exc)[:400]}"}

    is_sharpe = in_sample.get("sharpe_ratio")
    oos_sharpe = out_sample.get("sharpe_ratio")
    return {
        "config_diff": diff,
        "in_sample": in_sample,
        "out_sample": out_sample,
        "is_sharpe": is_sharpe,
        "oos_sharpe": oos_sharpe,
        "oos_return": out_sample.get("total_return"),
        "oos_max_drawdown": out_sample.get("max_drawdown"),
        "overfit_gap": (round(is_sharpe - oos_sharpe, 4)
                        if is_sharpe is not None and oos_sharpe is not None else None),
        "error_message": None,
    }
