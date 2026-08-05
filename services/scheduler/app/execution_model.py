"""Which CHAIN the scheduler runs, chosen by the active strategy's execution
model. PURE: no HTTP, no DB, no clock — the supervisor stays in main.py.

    target_portfolio     the legacy chain. Rank the universe, vet it, build a
                         normalised TARGET, diff it against the broker.
                         fetch-data -> pipeline -> vet -> portfolio-builder -> delta

    stateful_ownership   Wealth Core. There is no target to build and nothing to
                         diff against; the book IS the state.
                         sync -> wealth-core-session -> risk -> execute -> reconcile

WHY THIS HAS TO BE A ROUTING DECISION AND NOT A FLAG INSIDE THE CHAIN. The
legacy chain HALTS if any stage fails, and four of its five stages are
meaningless under Wealth Core: there is no factor composite to rank, no
discretionary exclusion to apply, and no target to construct. Leaving them in
the chain would mean the live book stops trading whenever a service it does not
use has a bad night — and, worse, that somebody eventually "fixes" the outage by
making Wealth Core consume a target, which is the one change that would silently
turn it into a different strategy (position age, review flag, episode peak and
both cooldowns cannot be recomputed from a target).

So the models are disjoint chains selected by the config, and the stages the
active model does not use are not merely tolerated when they fail — they are
NOT RUN and NOT WAITED FOR.

FAIL-CLOSED ON AN UNKNOWN MODEL. A config naming a model this scheduler does not
implement gets an error, never the legacy default. Defaulting would run a
target-diff chain against a stateful book, and the delta engine would happily
propose selling every position it did not recognise.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping


class ExecutionModel(str, Enum):
    TARGET_PORTFOLIO = "target_portfolio"
    STATEFUL_OWNERSHIP = "stateful_ownership"


DEFAULT_EXECUTION_MODEL = ExecutionModel.TARGET_PORTFOLIO
"""What a config that says nothing means. Every existing strategy predates this
field, and they are all target-portfolio strategies, so silence has an
unambiguous correct reading — unlike an unrecognised value, which does not."""


class UnknownExecutionModel(ValueError):
    """The config names a model this scheduler does not implement."""


@dataclass(frozen=True)
class ChainSpec:
    model: ExecutionModel
    steps: tuple[str, ...]
    description: str

    def runs(self, step: str) -> bool:
        return step in self.steps


TARGET_PORTFOLIO_CHAIN = ChainSpec(
    model=ExecutionModel.TARGET_PORTFOLIO,
    steps=("fetch-data", "pipeline", "vet", "portfolio-builder", "delta"),
    description="rank the universe, vet it, build a normalised target, diff it "
                "against the broker",
)

STATEFUL_OWNERSHIP_CHAIN = ChainSpec(
    model=ExecutionModel.STATEFUL_OWNERSHIP,
    steps=("broker-sync", "wealth-core-session", "risk-reserve", "execute",
           "broker-reconcile"),
    description="sync the account, advance the strategy one session, gate the "
                "explicit operations, submit them, reconcile the fills",
)

CHAINS: Mapping[ExecutionModel, ChainSpec] = {
    ExecutionModel.TARGET_PORTFOLIO: TARGET_PORTFOLIO_CHAIN,
    ExecutionModel.STATEFUL_OWNERSHIP: STATEFUL_OWNERSHIP_CHAIN,
}

# Legacy stages a stateful_ownership deploy must NOT require. Exported so the
# scheduler and its tests read one list; two copies would drift, and the drift
# would show up as a live book that stops trading when a service it does not use
# has a bad night.
LEGACY_STAGES_BYPASSED: tuple[str, ...] = tuple(
    s for s in TARGET_PORTFOLIO_CHAIN.steps
    if s not in STATEFUL_OWNERSHIP_CHAIN.steps)


def resolve(config: Mapping | None) -> ChainSpec:
    """Pick the chain from a strategy config mapping.

    Reads `execution_model` at the TOP LEVEL. Nested under a sub-section it
    would fall into the parts of the config that get treated as inert by
    config-replay and the parity manifests — the same trap the trailing-stop
    block was moved to the top level to avoid.
    """
    raw = (config or {}).get("execution_model")
    if raw is None:
        return CHAINS[DEFAULT_EXECUTION_MODEL]
    try:
        model = ExecutionModel(raw)
    except ValueError:
        raise UnknownExecutionModel(
            f"unknown execution_model {raw!r}; known: "
            f"{[m.value for m in ExecutionModel]}. Refused rather than "
            f"defaulted to {DEFAULT_EXECUTION_MODEL.value!r} — running a "
            f"target-diff chain against a stateful book would have the delta "
            f"engine propose selling every position it did not recognise."
        ) from None
    return CHAINS[model]


def steps_for(config: Mapping | None) -> tuple[str, ...]:
    return resolve(config).steps


@dataclass
class RunTrace:
    """A persisted record of WHICH chain actually ran and what it skipped.

    Written by a deployed run and kept as an artifact, because "Wealth Core does
    not require the target-portfolio stages" is a claim about runtime behaviour
    that no source reading can settle. The stages remain INSTALLED and may keep
    failing; the trace is what shows a Wealth Core run completed anyway.

    `bypassed_stage_health` records what those services were doing at the time —
    a trace taken while they all happened to be healthy proves considerably less
    than one taken while two of them were down.
    """
    execution_model: str
    session: str
    stages_invoked: list[str] = field(default_factory=list)
    stages_bypassed: list[str] = field(default_factory=list)
    bypassed_stage_health: dict = field(default_factory=dict)
    intents: int = 0
    orders_submitted: int = 0
    started_at: str | None = None
    completed_at: str | None = None
    notes: list[str] = field(default_factory=list)

    def validate(self) -> list[str]:
        """Problems with the trace itself, as data.

        Returns an empty list for a valid trace. Deliberately not raising: a
        trace is EVIDENCE, and a caller that cannot save a flawed one has no way
        to show what actually happened on a bad day.
        """
        problems: list[str] = []
        spec = CHAINS.get(ExecutionModel(self.execution_model))
        if spec is None:
            return [f"unknown execution_model {self.execution_model!r}"]

        expected = list(spec.steps)
        if self.stages_invoked != expected:
            problems.append(
                f"stage ORDER wrong: {self.stages_invoked} != {expected}. The "
                f"order is the contract — the account must be synced before the "
                f"session decides anything, since sizing is 4% of CURRENT "
                f"equity, and the risk gate must sit between the decision and "
                f"the broker.")
        leaked = sorted(set(self.stages_invoked) & set(LEGACY_STAGES_BYPASSED))
        if spec.model is ExecutionModel.STATEFUL_OWNERSHIP and leaked:
            problems.append(
                f"target-portfolio stage(s) {leaked} were INVOKED by a "
                f"stateful_ownership run")
        if spec.model is ExecutionModel.STATEFUL_OWNERSHIP:
            missing = sorted(set(LEGACY_STAGES_BYPASSED) - set(self.stages_bypassed))
            if missing:
                problems.append(f"stage(s) {missing} not recorded as bypassed")
        if self.orders_submitted and "LIVE" not in " ".join(self.notes):
            problems.append(
                "orders were submitted but the trace is not marked LIVE; a "
                "dry run must submit nothing")
        return problems

    def to_dict(self) -> dict:
        return {"execution_model": self.execution_model,
                "session": self.session,
                "stages_invoked": list(self.stages_invoked),
                "stages_bypassed": sorted(self.stages_bypassed),
                "bypassed_stage_health": dict(sorted(
                    self.bypassed_stage_health.items())),
                "intents": self.intents,
                "orders_submitted": self.orders_submitted,
                "started_at": self.started_at,
                "completed_at": self.completed_at,
                "notes": sorted(self.notes),
                "problems": self.validate(),
                "valid": not self.validate()}


__all__ = ["CHAINS", "ChainSpec", "RunTrace", "DEFAULT_EXECUTION_MODEL", "ExecutionModel",
           "LEGACY_STAGES_BYPASSED", "STATEFUL_OWNERSHIP_CHAIN",
           "TARGET_PORTFOLIO_CHAIN", "UnknownExecutionModel", "resolve",
           "steps_for"]
