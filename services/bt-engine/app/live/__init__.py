"""Loader for the LIVE pipeline/builder math the backtest engine re-runs.

Plan decision (docs/backtester-v2-plan.md): bt-engine reuses the SAME functions as
the live chain — compute_all_factors, detect_regime, rank_universe, the builder's
select.py, and the delta engine's evaluate_target_vs_live. Two load paths:

  IMAGE: the Dockerfile COPYs the real source files NEXT TO this __init__ at build
         time (services/pipeline/app/{factors,rank,regime,engine}.py and
         services/portfolio-builder/app/select.py → app/live/). Same files, zero
         drift, no vendor-sync tests needed.
  REPO (tests/dev): the files aren't copied; fall back to loading them straight
         from their service paths relative to the repo root.

Either way the modules are self-contained (numpy/pandas/stock_strategy_shared
only — verified), so they import cleanly without their home service.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
# repo root when running from a checkout: services/bt-engine/app/live → up 4
_REPO = _HERE.parents[3]

_SOURCES = {
    "factors": ("factors.py", "services/pipeline/app/factors.py"),
    "rank": ("rank.py", "services/pipeline/app/rank.py"),
    "regime": ("regime.py", "services/pipeline/app/regime.py"),
    "engine": ("engine.py", "services/pipeline/app/engine.py"),
    "select": ("select.py", "services/portfolio-builder/app/select.py"),
}


def _load(name: str):
    sibling, repo_rel = _SOURCES[name]
    for candidate in (_HERE / sibling, _REPO / repo_rel):
        if candidate.exists():
            modname = f"bt_live_{name}"
            if modname in sys.modules:
                return sys.modules[modname]
            spec = importlib.util.spec_from_file_location(modname, candidate)
            mod = importlib.util.module_from_spec(spec)
            sys.modules[modname] = mod
            spec.loader.exec_module(mod)
            return mod
    raise ImportError(f"live module {name!r} not found (looked at {sibling} and {repo_rel})")


factors = _load("factors")
rank = _load("rank")
regime = _load("regime")
engine = _load("engine")
select = _load("select")

compute_all_factors = factors.compute_all_factors
FACTORS = rank.FACTORS
rank_universe = rank.rank_universe
detect_regime = regime.detect_regime
resolve_confirmed_regime = regime.resolve_confirmed_regime
RankObservation = engine.RankObservation
evaluate_target_vs_live = engine.evaluate_target_vs_live
greedy_select = select.greedy_select
compute_weights = select.compute_weights
build_covariance = select.build_covariance
correlation_clusters = select.correlation_clusters
book_volatility = select.book_volatility
vol_target_exposure = select.vol_target_exposure
solve_beta_target_weights = select.solve_beta_target_weights
apply_all_caps = select._apply_all_caps
