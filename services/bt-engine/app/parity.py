"""Parity manifest: which StrategyConfig fields the wind tunnel actually honours.

The factor-coverage contract (app/coverage.py) closed one instance of a general
problem — a config says one thing and the tunnel scores another. `turnover_penalty`
was the same bug one layer up: live passed `current_holdings`/`turnover_penalty`
into greedy_select, the simulator did not, so any config with a nonzero penalty
was scored as though it were zero. Nothing announced that.

This module generalizes the rule to the whole config surface:

> Every parameter that can change live behaviour needs an explicit wind-tunnel
> parity declaration. Where the tunnel cannot model one, it REFUSES the config
> rather than scoring it as if the parameter were absent.

`check_config_parity(cfg)` returns violations for IGNORED fields whose value
DIFFERS FROM THE SCHEMA DEFAULT. Defaults are exempt on purpose: a field left at
its default is not something the author asked for, so refusing on it would refuse
every config for parameters nobody set.

Three verdicts:
    HONOURED  the tunnel models it (or it provably cannot affect a simulation)
    PARTIAL   modelled with a stated limitation — allowed, but it is a caveat
    IGNORED   not modelled at all — refused when set to a non-default value

Classification is BY DECLARATION, not inference, so adding a schema field fails
the drift test until someone decides which it is. That is the point: the previous
failures were all things nobody had to decide about.
"""
from __future__ import annotations

import os

from stock_strategy_shared.schemas.strategy import StrategyConfig

HONOURED = "honoured"
PARTIAL = "partial"
IGNORED = "ignored"

# Keys are dotted paths into the StrategyConfig dump. A bare section name
# classifies every field under it that has no more specific entry.
PARITY: dict[str, tuple[str, str]] = {
    # ── identity / documentation ──────────────────────────────────────────
    "strategy_id":  (HONOURED, "recorded on the run; affects nothing"),
    "description":  (HONOURED, "documentation only"),

    # ── universe ─────────────────────────────────────────────────────────
    "universe.min_price": (HONOURED, "below_investability_floor at selection"),
    "universe.min_avg_dollar_volume_20d": (HONOURED, "same floor, 20d ADV"),
    "universe.source": (
        PARTIAL,
        "the tunnel's universe is Sharadar TICKERS, not AV LISTING_STATUS. "
        "Listing/delisting WINDOWS are point-in-time; the sector LABEL is "
        "current-state (no vendor history)"),
    "universe.require_fundamentals": (
        IGNORED,
        "the tunnel does not drop fundamentals-less securities before the factor "
        "step — bt_fundamentals coverage differs from AV's, so applying it would "
        "filter a different set than live"),

    # ── factor engine ────────────────────────────────────────────────────
    "factor_engine": (
        HONOURED,
        "compute_all_factors is the SAME module live runs (module identity is "
        "asserted by tests/backtester/test_vendor_sync.py), so every knob under "
        "it takes effect identically"),

    # ── regime + weights ─────────────────────────────────────────────────
    "regime_detection": (HONOURED, "detect_regime + resolve_confirmed_regime, per date"),
    "factor_weights": (HONOURED, "via effective_factor_weights(regime)"),
    "static_factor_weights": (HONOURED, "via effective_factor_weights(regime)"),
    "regime_weighting_enabled": (HONOURED, "resolved by the config, not re-derived"),

    # ── ranking ──────────────────────────────────────────────────────────
    "max_positions": (HONOURED, "portfolio_builder.max_positions takes precedence"),
    "min_score_percentile": (
        IGNORED,
        "the tunnel selects from the candidate_count head by score and does not "
        "apply a separate percentile floor"),
    "min_non_null_factors": (HONOURED, "rank_universe, shared module"),
    "min_non_null_factors_scope": (HONOURED, "passed to composite_scores"),
    "min_ranked": (
        IGNORED,
        "the degraded-ranking FLAG is a live pipeline/DB concept "
        "(ranking_runs.degraded). The tunnel's equivalent safety is TargetStatus, "
        "which holds the book on a degraded build"),
    "required_factors": (HONOURED, "rank_universe, shared module"),
    "deduplicate_share_classes": (
        IGNORED,
        "share-class dedup runs in the live pipeline against AV listing metadata "
        "the tunnel does not carry"),

    # ── portfolio builder ────────────────────────────────────────────────
    "portfolio_builder.method": (HONOURED, "greedy_select, shared module"),
    "portfolio_builder.max_positions": (HONOURED, "greedy_select target"),
    "portfolio_builder.max_position_weight": (HONOURED, "compute_weights + cap loop"),
    "portfolio_builder.max_sector_weight": (HONOURED, "av_sector_map cap"),
    "portfolio_builder.max_cluster_weight": (HONOURED, "cluster cap"),
    "portfolio_builder.max_tickers_per_cluster": (HONOURED, "greedy count cap"),
    "portfolio_builder.cluster_correlation_threshold": (HONOURED, "correlation_clusters"),
    "portfolio_builder.weighting": (HONOURED, "compute_weights"),
    "portfolio_builder.candidate_count": (HONOURED, "ranked head size"),
    "portfolio_builder.covariance_window_days": (HONOURED, "build_covariance"),
    "portfolio_builder.min_covariance_observations": (HONOURED, "build_covariance"),
    "portfolio_builder.covariance_shrinkage": (HONOURED, "build_covariance"),
    "portfolio_builder.selection_vol_aversion": (HONOURED, "greedy_select"),
    "portfolio_builder.require_positive_composite_score": (HONOURED, "pre-selection filter"),
    "portfolio_builder.do_not_buy": (HONOURED, "candidate filter"),
    "portfolio_builder.cash_reserve": (HONOURED, "exposure scaling"),
    "portfolio_builder.vol_target_enabled": (HONOURED, "vol_target_exposure"),
    "portfolio_builder.vol_target": (HONOURED, "vol_target_exposure"),
    "portfolio_builder.vol_target_min_exposure": (HONOURED, "vol_target_exposure"),
    "portfolio_builder.beta_target_enabled": (HONOURED, "solve_beta_target_weights"),
    "portfolio_builder.beta_target": (HONOURED, "solve_beta_target_weights"),
    "portfolio_builder.beta_tolerance": (
        PARTIAL,
        "the solver runs but the tunnel does not re-check the realized tolerance"),
    "portfolio_builder.turnover_penalty": (
        HONOURED,
        "current_holdings + turnover_penalty are passed to greedy_select exactly "
        "as live does, gated on > 0. THIS WAS THE GAP that motivated the manifest"),
    "portfolio_builder.min_selected": (
        HONOURED,
        "INERT by construction: live uses it only to WARN when the cap is "
        "infeasible on a thin book. It changes no weights and no selection, so "
        "there is nothing for the tunnel to model"),

    # ── vetter ───────────────────────────────────────────────────────────
    "vetter.falling_knife": (HONOURED, "shared falling_knife_verdict, at selection"),
    "vetter.mode": (
        PARTIAL,
        "the tunnel always runs the DETERMINISTIC falling-knife veto. mode: llm "
        "cannot be replayed (an LLM judgement is not a function of the config), so "
        "an llm-mode config is scored as drawdown_only"),
    "vetter.candidate_count": (HONOURED, "vet pool = ranked head"),
    "vetter.enabled": (
        PARTIAL,
        "the falling-knife veto always applies in the tunnel; disabling the vetter "
        "live would remove it"),
    "vetter": (
        IGNORED,
        "LLM-vetting knobs (news/search budgets, prompts, strictness, horizons) "
        "describe a run-time LLM process with no deterministic replay"),

    # ── delta engine ─────────────────────────────────────────────────────
    "delta_engine.orphan_confirmation_days": (HONOURED, "evaluate_target_vs_live"),
    "delta_engine.confirmation_days": (HONOURED, "evaluate_target_vs_live"),
    "delta_engine.entry_rank": (HONOURED, "cold-start fallback only, as live"),
    "delta_engine.exit_rank": (HONOURED, "cold-start fallback only, as live"),
    "delta_engine.max_positions": (HONOURED, "capacity gate"),
    "delta_engine.rebalance_drift_threshold": (HONOURED, "drift trims"),
    "delta_engine.rebalance_min_relative_drift": (HONOURED, "drift trims"),
    "delta_engine.rebalance_min_trade_value": (HONOURED, "drift trims"),

    # ── intraday ─────────────────────────────────────────────────────────
    "intraday": (
        IGNORED,
        "the simulator steps DAILY bars; intraday monitoring/trims have no "
        "representation in it at all"),
}


def enforcement_enabled() -> bool:
    """Read per call — a safety gate must be flippable without an image rebuild."""
    return (os.getenv("BT_PARITY_ENFORCE", "true") or "").strip().lower() \
        not in ("false", "0", "no", "off")


def _flatten(d: dict, prefix: str = "") -> dict:
    out = {}
    for k, v in (d or {}).items():
        path = f"{prefix}{k}"
        # Only descend ONE level: the manifest classifies sections and their
        # immediate fields. Deeper structures (regimes, falling_knife) are
        # classified by their parent, which is what the declarations say.
        if isinstance(v, dict) and not prefix:
            out[path] = v
            for k2, v2 in v.items():
                out[f"{path}.{k2}"] = v2
        else:
            out[path] = v
    return out


def verdict_for(path: str) -> tuple[str, str]:
    """Most specific declaration wins; fall back to the section's."""
    if path in PARITY:
        return PARITY[path]
    section = path.split(".", 1)[0]
    if section in PARITY:
        return PARITY[section]
    return (IGNORED, "undeclared in the parity manifest")


def _is_inert(path: str, cfg: StrategyConfig) -> bool:
    """Is an IGNORED field unable to bite GIVEN THE REST of this config?

    Without this the manifest refuses every real config: the vetter's LLM knobs
    (prompt file, search budgets, strictness, news horizons) are all set in the
    active YAML but are dead code under `mode: drawdown_only`, which is the
    default and what every current config uses. A gate that fires on a field
    which cannot affect the run is noise, and a gate that is noise gets switched
    off."""
    if path.startswith("vetter."):
        return getattr(cfg.vetter, "mode", "drawdown_only") != "llm"
    return False


def check_config_parity(cfg: StrategyConfig) -> list[str]:
    """Violations: IGNORED fields set to something other than the schema default.

    Comparing against the DEFAULT rather than flagging every ignored field is
    what keeps this usable — a field nobody set is not a claim about behaviour,
    and refusing on it would refuse every config ever written."""
    defaults = _flatten(_default_dump())
    actual = _flatten(cfg.model_dump(mode="json"))
    out = []
    for path, value in sorted(actual.items()):
        # Sections are classified so their LEAVES inherit a verdict; the section
        # itself is not a setting anyone chose, so it is never a violation.
        if isinstance(value, dict):
            continue
        verdict, why = verdict_for(path)
        if verdict != IGNORED:
            continue
        if path not in defaults:
            continue          # no default to compare against (required field)
        if defaults[path] == value:
            continue          # left at default → not a claim about behaviour
        if _is_inert(path, cfg):
            continue
        out.append(
            f"'{path}' is set to {value!r} but the wind tunnel does not model it: "
            f"{why}. Scoring this config would report a result for a strategy "
            f"that differs from the one described.")
    return out


_DEFAULT_CACHE: dict | None = None


def _default_dump() -> dict:
    """A minimal VALID config, used only to read field defaults.

    Built from the real schema rather than hand-listing defaults, so the manifest
    cannot drift from them. Cached: constructing it is pure but not free, and
    check_config_parity runs per candidate in a sweep."""
    global _DEFAULT_CACHE
    if _DEFAULT_CACHE is not None:
        return _DEFAULT_CACHE
    w = {"momentum": 0.4, "quality": 0.2, "value": 0.2, "growth": 0.1,
         "low_volatility": 0.1}
    regimes = {
        "bull_calm": {"spy_above_slow_sma": True, "vol_above_threshold": False},
        "bull_stress": {"spy_above_slow_sma": True, "vol_above_threshold": True},
        "bear_stress": {"spy_above_slow_sma": False, "vol_above_threshold": True},
        "bear_calm": {"spy_above_slow_sma": False, "vol_above_threshold": False},
    }
    cfg = StrategyConfig(
        strategy_id="_parity_defaults",
        universe={},
        regime_detection={"regimes": regimes},
        factor_weights={k: w for k in regimes},
        static_factor_weights=w,
        portfolio_builder={},
        vetter={},
    )
    _DEFAULT_CACHE = cfg.model_dump(mode="json")
    return _DEFAULT_CACHE


def unclassified_fields() -> list[str]:
    """Every schema field must carry a declaration. Surfaced as a function so the
    drift test and a future /health probe share one answer — a NEW config field
    must fail CI until someone decides whether the tunnel honours it."""
    problems = []
    for path, value in sorted(_flatten(_default_dump()).items()):
        # Sections are never violations (only their leaves are), so requiring a
        # section-level declaration would be a rule with no consequence.
        if isinstance(value, dict):
            continue
        if path in PARITY:
            continue
        section = path.split(".", 1)[0]
        if section in PARITY:
            continue
        problems.append(path)
    return problems
