"""What CONFIG-REPLAY actually models — the backtester's parity declaration.

Same mechanism as the wind tunnel's (shared/stock_strategy_shared/parity.py),
different and materially SMALLER set of honoured fields. Written because the
evaluator's `run_backtest` tool posts here, not to bt-engine, and this service
had no gate of any kind: a candidate diff touching a field config-replay ignores
came back as a clean summary with a Sharpe, and the model read it as evidence.

THE DEFINING LIMITATION. config-replay re-ranks the PERSISTED point-in-time
`factor_scores` rows. It does not recompute factors from prices. So a diff that
changes HOW a factor is constructed — momentum window, volatility window, the
PE/PB cap, sector-neutralisation — cannot be modelled at all: the stored values
were computed under whatever factor-engine settings production was running that
day. Re-weighting existing factor values is a genuinely useful and much cheaper
question; it is simply a different one, and returning a number for the wrong
question is the failure this gate exists to stop.

Everything config-replay cannot model routes the author to the wind tunnel
(`queue_strategy_experiment`), which recomputes factors from raw prices.
"""
from __future__ import annotations

import os

from stock_strategy_shared.parity import (HONOURED, IGNORED,  # noqa: F401
                                          PARTIAL, ParityManifest)
from stock_strategy_shared.schemas.strategy import StrategyConfig

PARITY: dict[str, tuple[str, str]] = {
    "strategy_id": (HONOURED, "recorded on the run; affects nothing"),
    "description": (HONOURED, "documentation only"),

    # ── the big one ──────────────────────────────────────────────────────
    "factor_engine": (
        IGNORED,
        "config-replay re-ranks PERSISTED factor_scores; it does not recompute "
        "factors from prices. A factor-CONSTRUCTION change cannot be modelled "
        "here — the stored values were computed under production's settings for "
        "that date. Use queue_strategy_experiment (the wind tunnel), which "
        "recomputes factors from raw prices"),

    # ── ranking: re-weighting stored factors is exactly what this does ────
    "factor_weights": (HONOURED, "re-ranks the stored factor values"),
    "static_factor_weights": (HONOURED, "re-ranks the stored factor values"),
    "regime_weighting_enabled": (HONOURED, "resolved by the config"),
    "regime_detection": (
        PARTIAL,
        "regime is re-detected from SPY prices via the vendored regime module "
        "(byte-sync enforced, not module identity like rank/select)"),
    "min_non_null_factors": (HONOURED, "rank_universe, shared module"),
    "min_non_null_factors_scope": (HONOURED, "passed through rank_universe"),
    "required_factors": (HONOURED, "rank_universe, shared module"),
    "max_positions": (HONOURED, "portfolio_builder.max_positions takes precedence"),
    "min_score_percentile": (
        HONOURED,
        "applied INSIDE rank_universe (the shared module both engines call), not "
        "as a separate step afterwards — which is why it was mis-declared IGNORED "
        "until the behavioural harness caught it moving the target"),
    "min_ranked": (
        IGNORED,
        "the degraded-ranking flag is a live pipeline/DB concept; config-replay "
        "SKIPS a date whose build is empty, which silently extends the prior "
        "holding period instead of recording a degraded build"),
    "deduplicate_share_classes": (
        IGNORED, "share-class dedup uses live AV listing metadata not carried here"),

    # ── universe ─────────────────────────────────────────────────────────
    "universe.min_price": (HONOURED, "investability floor at selection"),
    "universe.min_avg_dollar_volume_20d": (HONOURED, "investability floor, 20d ADV"),
    "universe.require_fundamentals": (
        IGNORED, "no pre-factor fundamentals filter is applied"),
    "universe.source": (
        PARTIAL,
        "eligibility is inferred from PRICE PRESENCE, not from listing/delisting "
        "windows — so ticker reuse, reorganisations and listing gaps are not "
        "distinguished (the wind tunnel checks real listing windows)"),

    # ── portfolio builder: the shared select/weight path ─────────────────
    "portfolio_builder.method": (HONOURED, "greedy_select, shared module"),
    "portfolio_builder.max_positions": (HONOURED, "greedy_select target"),
    "portfolio_builder.max_position_weight": (HONOURED, "compute_weights + cap loop"),
    "portfolio_builder.max_sector_weight": (HONOURED, "av_sector cap"),
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
        PARTIAL, "the solver runs; the realized tolerance is not re-checked"),
    "portfolio_builder.min_selected": (
        HONOURED,
        "INERT by construction — live uses it only to WARN on a thin book; it "
        "changes no weights and no selection"),
    "portfolio_builder.turnover_penalty": (
        IGNORED,
        "config-replay is holdings-agnostic: build_target_for_date receives no "
        "prior holdings, so a nonzero penalty is silently scored as zero. The "
        "wind tunnel passes current_holdings and models it"),

    # ── vetter: NOTHING is applied, not even the deterministic veto ───────
    "vetter": (
        IGNORED,
        "config-replay applies NO exclusions — not the LLM vetter, and not the "
        "deterministic falling-knife veto that both live and the wind tunnel "
        "apply at selection. A name they reject can be selected here"),
    "vetter.candidate_count": (
        HONOURED, "only sizes the candidate head, which config-replay does honour"),

    # ── delta engine: replay is target-only ──────────────────────────────
    "delta_engine": (
        IGNORED,
        "config-replay produces synthetic TARGETS and hands them to the "
        "persisted-book simulator; it does not run the entry/exit/orphan state "
        "machine, so none of these knobs can change its result"),
    "crash_brake": (
        IGNORED,
        "PATH-DEPENDENT book-level exposure: it scales the whole book on a market "
        "signal and restores it later, which a holdings-agnostic replay composing "
        "a fresh target per date cannot represent. Wind tunnel only"),
    "delta_engine.exit_policy": (
        IGNORED,
        "PATH-DEPENDENT, unlike its section-mates: it decides which positions "
        "survive from one date to the next, and this replay holds no book to "
        "survive in. Score it in the wind tunnel (queue_strategy_experiment)"),
    "delta_engine.drift_rebalance_enabled": (
        IGNORED,
        "suppresses rebalancing of EXISTING positions, which a holdings-agnostic "
        "replay does not have. Wind tunnel only"),

    "intraday": (IGNORED, "daily bars only; intraday logic has no representation"),

    # ── trailing-stop exit ───────────────────────────────────────────────
    # NOT inert, unlike delta_engine above — and that asymmetry is the point.
    # delta_engine knobs only steer a state machine config-replay never runs, so
    # they provably change nothing here. A trailing stop changes which positions
    # EXIST over time: it is path-dependent, and config-replay is holdings-agnostic
    # by construction (it composes a fresh target per date and never models a
    # position's history). Scoring a stop-enabled candidate here would silently
    # report the number for a strategy WITHOUT the stop. So this one must bite —
    # the evaluator's run_backtest tool gets a 422 pointing at the wind tunnel,
    # which is the only engine that can answer the question.
    "trailing_stop": (
        IGNORED,
        "config-replay is holdings-agnostic — it composes a target per date and "
        "never carries a position's entry or peak, so a path-dependent exit rule "
        "cannot be modelled at all. Score it in the wind tunnel "
        "(queue_strategy_experiment), which steps positions day by day"),
}


def _is_inert(path: str, cfg: StrategyConfig) -> bool:
    """An IGNORED field that cannot bite given the rest of THIS config.

    delta_engine is the interesting case: config-replay never runs the state
    machine, so its knobs are inert ALWAYS — but declaring them HONOURED would
    be a lie, and refusing on them would block every real config (they are all
    set). IGNORED-but-inert is the honest encoding: the declaration says "not
    modelled", the gate stays quiet because it provably changes nothing here.

    TWO EXCEPTIONS, and the distinction is exactly the one the inert claim rests
    on. `exit_policy` and `drift_rebalance_enabled` do not merely steer a state
    machine this replay skips — they decide WHICH POSITIONS EXIST over time, and
    config-replay is holdings-agnostic by construction (fresh target per date, no
    book to carry a holding forward in). Calling them inert would be the same
    class of lie the trailing-stop entry below refuses to tell. A stop-only
    config is already caught via trailing_stop.enabled, but only as a side
    effect; naming these directly means the 422 says what is actually wrong."""
    if path in ("delta_engine.exit_policy", "delta_engine.drift_rebalance_enabled"):
        return False
    return path.startswith("delta_engine.")


def enforcement_enabled() -> bool:
    """Read per call — a safety gate must be flippable without a rebuild."""
    return (os.getenv("BACKTESTER_PARITY_ENFORCE", "true") or "").strip().lower() \
        not in ("false", "0", "no", "off")


MANIFEST = ParityManifest("config-replay", PARITY, _is_inert)


def verdict_for(path: str) -> tuple[str, str]:
    return MANIFEST.verdict_for(path)


def check_config_parity(cfg: StrategyConfig,
                        baseline: StrategyConfig | None = None) -> list[str]:
    """Violations relative to `baseline` — normally the ACTIVE config.

    Baseline matters here in a way it does not for the wind tunnel. The stored
    factor_scores were computed by production under the ACTIVE factor-engine
    settings, so a candidate that leaves factor_engine alone is served correctly
    by them; only a CHANGE is unmodellable. With no baseline this falls back to
    schema defaults, which would refuse the active config itself."""
    return MANIFEST.check(cfg, baseline=baseline)


def unclassified_fields() -> list[str]:
    return MANIFEST.unclassified()
