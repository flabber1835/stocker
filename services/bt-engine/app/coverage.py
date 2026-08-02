"""Factor-coverage contract: the wind tunnel may not score a config that puts
nonzero weight on a factor it cannot compute.

WHY THIS EXISTS. The former champion `momentum_rotation_v2` weighted
`earnings_surprise` at 0.12.
bt-engine never passed `earnings=` to compute_all_factors and bt-data never
ingested earnings, so the factor was null on every row. `composite_scores`
renormalizes per row over the NON-NULL factors — correct for a transiently
missing value, catastrophic for a structurally absent one: instead of erroring,
it redistributed the 0.12 and quietly scored momentum at 0.409 rather than
0.360. Every wind-tunnel run was scoring a config that was not the one supplied,
and auto-promotion could act on the result.

STATUS 2026-08: the active config `momentum_core_v3` sets earnings_surprise to 0,
so it now PASSES this gate and is scoreable — which was one of the reasons for
the change, not a side effect. Auto-promotion is no longer blocked by the active
config. The gate itself stays exactly as strict: the moment any config weights a
factor the corpus cannot reproduce, it is refused again. Teaching the tunnel the
factor remains the right resolution; dropping a factor to satisfy the instrument
would be letting the instrument dictate the strategy, and that is NOT what
happened here (the weight went to 0 on its own evidence — a seasonal-random-walk
SUE is a weak proxy for estimate-revision data).

The renormalizer cannot distinguish "this ticker has no earnings yet" from "this
corpus has no earnings at all". So the distinction has to be made here, before
the run starts.

TWO CHECKS, both needed:

  static (check_config_coverage)  — declaration-based, at request time. Fast,
    fails before any compute. But the declaration is hand-maintained and can go
    stale as bt-data's ingest changes.
  empirical (CoverageObserver)    — was each weighted factor EVER observed
    non-null across the whole run? Cannot lie, but only answers at the end.

A factor is checked against every weight vector the config could ACTUALLY use.
That is resolved through `StrategyConfig.effective_factor_weights(regime)` rather
than by re-deriving the regime_weighting_enabled rule here — a second copy of
that rule is exactly the drift this module exists to prevent.
"""
from __future__ import annotations

import os

from stock_strategy_shared.factor_registry import FACTOR_NAMES
from stock_strategy_shared.schemas.strategy import StrategyConfig

# Every regime a config can resolve weights for. Kept explicit so a new regime
# added to the schema without updating this list shows up as a KeyError in tests
# rather than as a silently unchecked weight vector.
_REGIMES = ("bull_calm", "bull_stress", "bear_stress", "bear_calm")

# What bt-engine can compute, and the INPUT each one needs. Written as a mapping
# rather than a bare set so the declaration reads as a contract: if you cannot
# name the column that feeds a factor, it does not belong here.
#
# Inputs available to sim.build_target:
#   day_prices        — bt_prices: ticker, date, open, close, adjusted_close, volume
#   fundamentals_asof — bt_fundamentals, point-in-time by as_of_date
SUPPORTED_FACTORS: dict[str, str] = {
    "momentum":         "bt_prices.adjusted_close",
    "low_volatility":   "bt_prices.adjusted_close",
    "high_volatility":  "bt_prices.adjusted_close (inverse of low_volatility)",
    "near_high":        "bt_prices.adjusted_close",
    "volume_surge":     "bt_prices.volume",
    "liquidity":        "bt_prices.close + volume",
    "quality":          "bt_fundamentals.roe / debt_to_equity "
                        "(+ gross_profit / total_assets when "
                        "quality_use_gross_profitability — see DEFINITION_INPUTS)",
    "value":            "bt_fundamentals.pe_ratio / pb_ratio",
    "growth":           "bt_fundamentals.revenue_growth / eps_growth",
    "small_cap":        "bt_fundamentals.market_cap",
    "issuance":         "bt_fundamentals.shares_outstanding[_prior]",
}

# Declared explicitly rather than inferred as "everything else", so adding a
# factor to the registry without deciding its wind-tunnel status fails the drift
# test instead of defaulting to either answer.
UNSUPPORTED_FACTORS: dict[str, str] = {
    # CONDITIONAL: computable under sue_method='seasonal_random_walk' (which
    # needs only reported eps, in bt_earnings), NOT under 'analyst' (which needs
    # estimates Sharadar does not carry). See _supports_earnings_surprise.
    "earnings_surprise":
        "sue_method='analyst' needs analyst estimates, which the Sharadar corpus "
        "does not carry. Switch to sue_method='seasonal_random_walk' — the "
        "classic Foster-Olsen-Shevlin SUE (eps_q − eps_{q-4}), which BOTH live "
        "and this corpus can compute identically",
}


def _supports_earnings_surprise(config: StrategyConfig) -> bool:
    """The one factor whose support depends on HOW it is configured.

    Method-aware rather than a blanket refusal: the gate exists to stop a config
    being scored differently than it reads, not to ban a factor. Under SRW the
    tunnel computes exactly what live computes."""
    return getattr(config.factor_engine, "sue_method", "") == "seasonal_random_walk"


class CoverageError(RuntimeError):
    """A run produced numbers for a config the corpus cannot actually score.

    Its own type so the sweep's per-config handler can distinguish a coverage
    failure from an ordinary simulation error in the result row."""


def enforcement_enabled() -> bool:
    """Read per call, not at import: the contract is a safety gate and must be
    flippable without rebuilding the image."""
    return (os.getenv("BT_COVERAGE_ENFORCE", "true") or "").strip().lower() \
        not in ("false", "0", "no", "off")


def weighted_factors(config: StrategyConfig) -> dict[str, float]:
    """Every factor carrying nonzero weight in any regime the config could
    resolve, mapped to its LARGEST such weight (used only for the message).

    Goes through effective_factor_weights() so `regime_weighting_enabled: false`
    is honoured — a static-weight config must not be judged on the four regime
    vectors it never consults."""
    out: dict[str, float] = {}
    for regime in _REGIMES:
        weights = config.effective_factor_weights(regime).model_dump()
        for name, w in weights.items():
            try:
                w = abs(float(w))
            except (TypeError, ValueError):
                continue
            if w > 0 and w > out.get(name, 0.0):
                out[name] = w
    return out


def check_config_coverage(config: StrategyConfig) -> list[str]:
    """Static gate. Returns a list of human-readable violations (empty = OK).

    Returns violations even when enforcement is disabled — the caller decides
    whether to reject or merely log, so the diagnosis is always available."""
    violations: list[str] = []
    for name, weight in sorted(weighted_factors(config).items()):
        if name in SUPPORTED_FACTORS:
            continue
        if name == "earnings_surprise" and _supports_earnings_surprise(config):
            continue
        reason = UNSUPPORTED_FACTORS.get(
            name, "not computable by bt-engine (unknown factor)")
        violations.append(
            f"'{name}' carries weight {weight:g} but the wind tunnel cannot "
            f"compute it: {reason}. Scoring it anyway would renormalize the "
            f"weight across the remaining factors and silently test a "
            f"DIFFERENT strategy.")
    return violations


# ── the blind spot both checks above share ───────────────────────────────────
#
# Everything above asks "is the factor non-null?". A factor with a GRACEFUL
# DEGRADATION PATH answers yes while computing something else entirely, so
# neither check can see it.
#
# The instance that motivated this: `quality_use_gross_profitability: true` —
# set by every strategy config in the repo — makes the quality factor
# gross-profits-to-assets (Novy-Marx). `compute_quality` falls back to ROE PER
# TICKER when gp/assets are missing, which is exactly right for one ticker's
# vendor blip. bt-data never mapped SF1's `gp`/`assets`, so the tunnel took that
# fallback for EVERY ticker on EVERY date and scored ROE-quality — a different
# factor, at 25% of the live composite — while `quality` stayed perfectly
# non-null and both checks above passed.
#
# So the question here is not "did it compute?" but "did it compute the
# DEFINITION the config asked for?". Each entry names a config switch, the input
# columns that switch requires, and what the code silently does without them.
# Add an entry whenever a factor gains a fallback; a fallback with no entry is
# the same bug again.
DEFINITION_INPUTS: dict[str, dict] = {
    "quality_use_gross_profitability": {
        "factor": "quality",
        "columns": ("gross_profit", "total_assets"),
        "fallback": "ROE (the legacy proxy), per ticker",
        "source": "Sharadar SF1 gp / assets, mapped by bt-data",
    },
}


def check_definition_coverage(config: StrategyConfig, fundamentals) -> list[str]:
    """Did the corpus carry the inputs for the factor DEFINITIONS this config
    selected? Returns human-readable violations (empty = OK).

    Judged on the WHOLE corpus, never per ticker: a name whose filing lacks gross
    profit legitimately falls back, and refusing that would be refusing the
    fallback's entire reason for existing. "Not one row in the whole run" is the
    only reading with no innocent explanation — the same standard CoverageObserver
    applies to null factors.

    Cheap enough to run before the simulation starts, unlike the observer, because
    the inputs are a property of the loaded frame rather than of the run.
    """
    fe = getattr(config, "factor_engine", None)
    if fe is None or fundamentals is None:
        return []
    violations: list[str] = []
    for switch, spec in sorted(DEFINITION_INPUTS.items()):
        if not getattr(fe, switch, False):
            continue
        cols = getattr(fundamentals, "columns", ())
        missing = [c for c in spec["columns"]
                   if c not in cols or not bool(fundamentals[c].notna().any())]
        if not missing:
            continue
        violations.append(
            f"factor_engine.{switch} is on, but {', '.join(missing)} "
            f"{'is' if len(missing) == 1 else 'are'} absent from the corpus "
            f"({spec['source']}). '{spec['factor']}' would silently fall back to "
            f"{spec['fallback']} — a DIFFERENT factor under the same name, which "
            f"the non-null coverage checks cannot detect because the column comes "
            f"out fully populated.")
    return violations


class CoverageObserver:
    """Empirical backstop: did each weighted factor EVER produce a real value?

    Deliberately end-of-run, not first-rebalance. A factor can legitimately be
    all-null early (warm-up, sparse fundamentals at the start of a window), so
    failing on the first frame would produce false positives on exactly the
    thin-data configs the tunnel is meant to explore. "Never once, across the
    entire simulation" has no innocent explanation.
    """

    def __init__(self, config: StrategyConfig) -> None:
        self.weighted = weighted_factors(config)
        self.observed: set[str] = set()
        self.frames = 0

    def observe(self, factor_frame) -> None:
        """Record which weighted factors are non-null in one rebalance's frame."""
        if factor_frame is None or getattr(factor_frame, "empty", True):
            return
        self.frames += 1
        for name in self.weighted:
            if name in self.observed or name not in factor_frame.columns:
                continue
            try:
                if bool(factor_frame[name].notna().any()):
                    self.observed.add(name)
            except (AttributeError, TypeError):
                continue

    def violations(self) -> list[str]:
        """Weighted factors never seen non-null. Empty when nothing was
        observed at all — a run with zero factor frames failed for some other
        reason and must not be misdiagnosed as a coverage problem."""
        if self.frames == 0:
            return []
        return [
            f"'{name}' carries weight {self.weighted[name]:g} but was null on "
            f"every one of {self.frames} rebalance(s) — its weight was "
            f"renormalized away, so this run did not score the config supplied. "
            f"Either the corpus lacks its input, or the window is too short / "
            f"starts inside the factor's warm-up runway for it to ever compute."
            for name in sorted(set(self.weighted) - self.observed)
        ]


def registry_is_fully_classified() -> list[str]:
    """Every registry factor must be declared supported or unsupported, and
    never both. Surfaced as a function so the drift test and a future /health
    probe share one answer."""
    problems = []
    for name in FACTOR_NAMES:
        in_s, in_u = name in SUPPORTED_FACTORS, name in UNSUPPORTED_FACTORS
        if in_s and in_u:
            problems.append(f"'{name}' declared both supported and unsupported")
        elif not in_s and not in_u:
            problems.append(
                f"'{name}' is in the factor registry but undeclared in "
                f"coverage.py — decide whether the wind tunnel can compute it")
    for name in list(SUPPORTED_FACTORS) + list(UNSUPPORTED_FACTORS):
        if name not in FACTOR_NAMES:
            problems.append(f"'{name}' declared in coverage.py is not a registry factor")
    return problems
