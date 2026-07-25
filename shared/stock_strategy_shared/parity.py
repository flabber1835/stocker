"""Parity-manifest MECHANISM, shared by every historical simulator.

There are two systems that claim to answer "what would this config have done?" —
bt-engine (the wind tunnel) and the backtester's config-replay — and they model
DIFFERENT subsets of StrategyConfig. Each needs its own DECLARATION of what it
honours; neither should own a private copy of the logic that interprets one.
Two copies of a rule is the drift that has repeatedly bitten this system, so the
declarations live per-service and the engine lives here.

The rule both enforce:

> Every parameter that can change live behaviour needs an explicit parity
> declaration. Where a simulator cannot model one, it REFUSES the config rather
> than scoring it as if the parameter were absent.

Violations are raised only for fields set to a NON-DEFAULT value. A field nobody
set is not a claim about behaviour, so refusing on it would refuse every config
ever written.

NOTE FOR DEPLOYS: a NEW module file under shared/ — `stocker-base` must be
rebuilt before the services that import it (the editable install caches the
module file list).
"""
from __future__ import annotations

from typing import Callable, Optional

from stock_strategy_shared.schemas.strategy import StrategyConfig

HONOURED = "honoured"   # modelled, or provably unable to affect a simulation
PARTIAL = "partial"     # modelled with a stated limitation — allowed, a caveat
IGNORED = "ignored"     # not modelled — refused when set to a non-default value

VERDICTS = (HONOURED, PARTIAL, IGNORED)


def flatten_config(d: dict) -> dict:
    """One level deep: sections and their immediate fields.

    Deeper structures (regime_detection.regimes, vetter.falling_knife) are
    classified by their parent, which is what the declarations say."""
    out: dict = {}
    for k, v in (d or {}).items():
        out[k] = v
        if isinstance(v, dict):
            for k2, v2 in v.items():
                out[f"{k}.{k2}"] = v2
    return out


_DEFAULTS: Optional[dict] = None


def default_config_dump() -> dict:
    """A minimal VALID config, used only to read field defaults.

    Built from the real schema rather than hand-listing defaults, so a manifest
    can never drift from them. Cached — it is pure but not free, and the check
    runs per candidate in a sweep."""
    global _DEFAULTS
    if _DEFAULTS is not None:
        return _DEFAULTS
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
    _DEFAULTS = cfg.model_dump(mode="json")
    return _DEFAULTS


class ParityManifest:
    """One simulator's declaration of what it models.

    `inert` answers "can this IGNORED field bite GIVEN THE REST of this config?".
    Without it a manifest refuses every real config over settings that are dead
    code in the configured mode — and a gate that fires on something which cannot
    affect the run is noise, which gets switched off."""

    def __init__(self, engine: str, declarations: dict[str, tuple[str, str]],
                 inert: Optional[Callable[[str, StrategyConfig], bool]] = None):
        self.engine = engine
        self.declarations = declarations
        self._inert = inert or (lambda path, cfg: False)

    def verdict_for(self, path: str) -> tuple[str, str]:
        """Most specific declaration wins; fall back to the section's.

        An UNDECLARED path is IGNORED — fail-closed. An unknown field is assumed
        unmodelled, never assumed fine."""
        if path in self.declarations:
            return self.declarations[path]
        section = path.split(".", 1)[0]
        if section in self.declarations:
            return self.declarations[section]
        return (IGNORED, "undeclared in the parity manifest")

    def check(self, cfg: StrategyConfig,
              baseline: Optional[StrategyConfig] = None) -> list[str]:
        """Violations: IGNORED fields whose value DIFFERS FROM THE BASELINE.

        The baseline is what "unset" means for this simulator, and the two
        simulators genuinely differ:

        wind tunnel   baseline = the SCHEMA DEFAULTS. It recomputes everything
                      from raw data, so a field it ignores is unmodelled no
                      matter what anyone else was running.
        config-replay baseline = the ACTIVE CONFIG. It re-ranks factor_scores
                      that PRODUCTION computed, so a candidate whose
                      factor_engine matches production is correctly served by
                      those stored values — only a CHANGE to factor construction
                      is unmodellable. Comparing it against schema defaults
                      would refuse the active config itself, which is both wrong
                      and the fastest way to get a gate switched off."""
        defaults = flatten_config(
            baseline.model_dump(mode="json") if baseline is not None
            else default_config_dump())
        actual = flatten_config(cfg.model_dump(mode="json"))
        out: list[str] = []
        for path, value in sorted(actual.items()):
            # Sections are classified so their LEAVES inherit a verdict; the
            # section itself is not a setting anyone chose.
            if isinstance(value, dict):
                continue
            verdict, why = self.verdict_for(path)
            if verdict != IGNORED:
                continue
            if path not in defaults or defaults[path] == value:
                continue
            if self._inert(path, cfg):
                continue
            out.append(
                f"'{path}' is set to {value!r} but {self.engine} does not model "
                f"it: {why}. Scoring this config would report a result for a "
                f"strategy that differs from the one described.")
        return out

    def unclassified(self) -> list[str]:
        """Every schema LEAF must carry a declaration, so a new config field
        fails CI until someone decides. Sections need none — they are never
        violations, so requiring one would be a rule with no consequence."""
        problems = []
        for path, value in sorted(flatten_config(default_config_dump()).items()):
            if isinstance(value, dict):
                continue
            if path in self.declarations:
                continue
            if path.split(".", 1)[0] in self.declarations:
                continue
            problems.append(path)
        return problems

    def fields_with(self, verdict: str) -> list[str]:
        """Leaf paths carrying a verdict — the input to a behavioural test that
        checks the DECLARATION against what the simulator actually does."""
        out = []
        for path, value in sorted(flatten_config(default_config_dump()).items()):
            if isinstance(value, dict):
                continue
            if self.verdict_for(path)[0] == verdict:
                out.append(path)
        return out
