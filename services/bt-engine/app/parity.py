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

The MECHANISM lives in shared/stock_strategy_shared/parity.py — the backtester's
config-replay declares its own (different, smaller) set against the same engine,
and two copies of the interpreting logic is the drift this system keeps hitting.
This module is the wind tunnel's DECLARATION.

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

from stock_strategy_shared.parity import (HONOURED, IGNORED, PARTIAL,  # noqa: F401
                                          ParityManifest)
from stock_strategy_shared.schemas.strategy import StrategyConfig

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
        HONOURED,
        "applied INSIDE rank_universe (the shared module both engines call), not "
        "as a separate step afterwards — which is why it was mis-declared IGNORED "
        "until the behavioural harness caught it moving the target"),
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

    # ── trailing-stop exit ───────────────────────────────────────────────
    # One section declaration covers every leaf: verdict_for falls back to the
    # section, and unclassified()/check() skip dict values.
    "trailing_stop": (
        PARTIAL,
        "the stop itself IS simulated (per-position peak close, arming, staleness "
        "and the circuit breaker), but two limits are real. (1) CADENCE: live "
        "evaluates the stop every chain run (daily); this simulator's decision "
        "block is gated on rebalance_every, so a sweep at rebalance_every>1 checks "
        "the stop less often than live and a swept stop_pct carries that latency "
        "baked in. Run rebalance_every=1 to score it faithfully. (2) VINTAGE: live "
        "peaks come from AV adjusted closes, which are re-based only when AV "
        "restates them; this corpus is Sharadar SEP, uniformly restated end to "
        "end, so the tunnel cannot reproduce a live vintage split. Upgrade to "
        "HONOURED once the stop runs in the daily loop independent of the "
        "rebalance gate"),
}


def enforcement_enabled() -> bool:
    """Read per call — a safety gate must be flippable without an image rebuild."""
    return (os.getenv("BT_PARITY_ENFORCE", "true") or "").strip().lower() \
        not in ("false", "0", "no", "off")


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



MANIFEST = ParityManifest("this wind tunnel", PARITY, _is_inert)


def verdict_for(path: str) -> tuple[str, str]:
    return MANIFEST.verdict_for(path)


def check_config_parity(cfg: StrategyConfig) -> list[str]:
    return MANIFEST.check(cfg)


def unclassified_fields() -> list[str]:
    return MANIFEST.unclassified()


def config_identity(cfg) -> dict:
    """{config_hash, strategy_id} for a StrategyConfig. Pure.

    Hashed from CONTENT (sorted JSON of the validated model), not from the file
    bytes, and with the SAME algorithm the evaluator uses when it queues a
    candidate — so a baseline hash and a candidate hash are directly comparable
    and "which config was this measured against?" is answerable by equality."""
    import hashlib
    import json as _json
    try:
        d = cfg.model_dump(mode="json")
    except Exception:  # noqa: BLE001 — identity must never break a run
        return {"config_hash": None, "strategy_id": None}
    return {
        "config_hash": hashlib.sha256(
            _json.dumps(d, sort_keys=True, default=str).encode()).hexdigest()[:16],
        "strategy_id": d.get("strategy_id"),
    }


def run_provenance(cfg=None) -> dict:
    """The conditions under which a result was produced, stamped into every
    summary.

    A run made with a gate DISABLED used to be byte-indistinguishable from one
    made with it enforcing, so the promotion gate — deterministic code that
    rewrites the live strategy — could accept a candidate scored under no parity
    check at all. Read per call, like the gates themselves.

    `cfg` adds WHICH config produced the number. The yardstick used to record
    only the strategy NAME, so when a baseline re-ran and its excess-vs-SPY
    moved 2.5pp, telling a config change apart from a window phase-shift needed
    a filesystem mtime — evidence a redeploy would have destroyed. The identity
    of a measurement's input is not optional metadata."""
    from app.coverage import enforcement_enabled as coverage_enforcing
    out = {
        "parity_enforced": enforcement_enabled(),
        "coverage_enforced": coverage_enforcing(),
    }
    if cfg is not None:
        out.update(config_identity(cfg))
    return out
