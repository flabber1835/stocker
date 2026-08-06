"""Wealth Core in the WIND TUNNEL. Two modes, one state machine.

THE CONSTRAINT THIS FILE EXISTS TO SATISFY: the wind tunnel may not reproduce
eligibility, ranking, review, stop, cooldown, reservation or sizing logic. It
calls `run_with_hashes` and does nothing else that could constitute a decision.

That is not a stylistic preference. The tunnel's whole purpose is to say "this
change would have done better", and a tunnel with its own copy of the strategy
answers a different question — it reports how a REIMPLEMENTATION would have
done, and the two drift apart silently because nothing ever compares them. The
existing factor-coverage contract was written after exactly that happened at the
factor layer, where the tunnel scored ROE-quality under a GPA config for months
with every check green.

    BASELINE_REPLAY   run the reference stream and REQUIRE all seven parity
                      hashes to equal the backtester's. Produces no opinion; its
                      only output is pass or the first diverging layer.
    EXPERIMENT        run a modified stream or config, record the baseline
                      PARENT hashes, the exact change, and the first layer at
                      which it diverged.

An experiment that diverges at `normalized_input` is not an experiment — it
changed the data, not the strategy — and that is reported rather than scored,
because a config comparison across two different datasets is the most persuasive
wrong answer this system can produce.
"""
from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Sequence

from stock_strategy_shared.wealth_core.eligibility import EligibilityConfig
from stock_strategy_shared.wealth_core.engine import WealthCoreConfig
from stock_strategy_shared.wealth_core.performance import measure_run_result
from stock_strategy_shared.wealth_core.feed import SecurityMeta, VendorBar
from stock_strategy_shared.wealth_core.hashes import (
    HASH_ORDER,
    ParityHashes,
    divergence_report,
    first_divergence,
)
from stock_strategy_shared.wealth_core.run import run_with_hashes
from stock_strategy_shared.wealth_core.terminal import TerminalTerms


class TunnelMode(str, Enum):
    BASELINE_REPLAY = "BASELINE_REPLAY"
    EXPERIMENT = "EXPERIMENT"


class ParityViolation(RuntimeError):
    """A baseline replay did not reproduce the backtester.

    Its own type so a sweep can fail loudly instead of recording a result. A
    tunnel that has drifted from the backtester must not score anything: every
    number it produces afterwards is about a strategy nobody is running.
    """


@dataclass
class TunnelRun:
    mode: TunnelMode
    hashes: ParityHashes
    result: Any
    starting_cash: float = 0.0
    baseline_parent: dict | None = None
    change: dict = field(default_factory=dict)
    divergence: dict | None = None

    def to_dict(self) -> dict:
        return {"mode": self.mode.value,
                "hashes": self.hashes.to_dict(),
                "baseline_parent": self.baseline_parent,
                "change": self.change,
                "divergence": self.divergence,
                "final_cash": round(self.result.state.cash, 2),
                "final_positions": len(self.result.state.episodes),
                "marked_equity": (None if not self.result.final
                                  else self.result.final.marked_equity),
                # The SAME shared implementation the chain rehearsal uses. The
                # rehearsal establishes the baseline and an experiment is
                # measured against it; two local copies of the formulas would
                # make that a comparison between definitions rather than runs.
                # Derived output — it reaches no parity hash.
                "performance": measure_run_result(
                    self.result, self.starting_cash).to_dict()}


def _run(sessions, bars_by_session, meta, starting_cash, cfg, elig, terminal):
    return run_with_hashes(sessions=list(sessions),
                           bars_by_session=bars_by_session, meta=meta,
                           starting_cash=starting_cash, cfg=cfg,
                           eligibility_cfg=elig, terminal_events=terminal)


def baseline_replay(*, sessions: Sequence[str],
                    bars_by_session: Mapping[str, Sequence[VendorBar]],
                    meta: Mapping[str, SecurityMeta],
                    starting_cash: float,
                    expected: Mapping[str, str] | ParityHashes,
                    cfg: WealthCoreConfig | None = None,
                    eligibility_cfg: EligibilityConfig | None = None,
                    terminal_events: Sequence[TerminalTerms] = (),
                    ) -> TunnelRun:
    """Run the reference stream and REQUIRE exact equality on all seven hashes.

    `expected` comes from the backtester. It is an input rather than something
    recomputed here, because a tunnel that derives its own expectation proves
    only that it agrees with itself.
    """
    result, hashes = _run(sessions, bars_by_session, meta, starting_cash, cfg,
                          eligibility_cfg, terminal_events)
    diff = divergence_report(hashes, expected, left="tunnel", right="backtester")
    if not diff["identical"]:
        raise ParityViolation(
            f"wind tunnel diverges from the backtester at "
            f"{diff['first_divergence']!r}: {diff['interpretation']}. "
            f"Refusing to score anything — a tunnel that has drifted reports on "
            f"a strategy nobody is running. Full report: "
            f"{json.dumps(diff, sort_keys=True)}")
    return TunnelRun(mode=TunnelMode.BASELINE_REPLAY, hashes=hashes,
                     result=result, starting_cash=starting_cash,
                     divergence=diff)


def experiment(*, sessions: Sequence[str],
               bars_by_session: Mapping[str, Sequence[VendorBar]],
               meta: Mapping[str, SecurityMeta],
               starting_cash: float,
               baseline: Mapping[str, str] | ParityHashes,
               change: Mapping[str, Any],
               cfg: WealthCoreConfig | None = None,
               eligibility_cfg: EligibilityConfig | None = None,
               terminal_events: Sequence[TerminalTerms] = (),
               ) -> TunnelRun:
    """Run a variant and record what changed and where it first diverged.

    `change` is REQUIRED and must be non-empty. An experiment with no recorded
    change is indistinguishable from a failed baseline replay after the fact,
    and the whole value of the parent hashes is that a result can be traced to
    the exact modification that produced it.
    """
    if not change:
        raise ValueError(
            "an EXPERIMENT must record its change. Without it a result cannot "
            "be traced to what produced it, and is indistinguishable from a "
            "baseline replay that silently failed.")
    result, hashes = _run(sessions, bars_by_session, meta, starting_cash, cfg,
                          eligibility_cfg, terminal_events)
    diff = divergence_report(hashes, baseline, left="experiment",
                             right="baseline")
    parent = (baseline.values if isinstance(baseline, ParityHashes)
              else dict(baseline))
    run = TunnelRun(mode=TunnelMode.EXPERIMENT, hashes=hashes, result=result,
                    starting_cash=starting_cash, baseline_parent=parent,
                    change=dict(change), divergence=diff)
    if diff["first_divergence"] == "normalized_input":
        # Reported, not scored. Comparing two configs across two different
        # datasets is the most persuasive wrong answer this system can produce.
        run.divergence = dict(diff, warning=(
            "this experiment changed the DATA, not the strategy: it diverges at "
            "normalized_input, so any performance difference is confounded and "
            "must not be attributed to the change"))
    return run


def apply_config_change(cfg: WealthCoreConfig,
                        change: Mapping[str, Any]) -> WealthCoreConfig:
    """Build the experiment config from a field diff over the baseline.

    Refuses unknown fields. `dataclasses.replace` would accept only real fields
    anyway, but it raises a TypeError naming Python internals; a change set
    typo'd by an author or an LLM deserves an error that names the field and
    lists what exists.
    """
    known = {f.name for f in dataclasses.fields(WealthCoreConfig)}
    unknown = sorted(set(change) - known)
    if unknown:
        raise ValueError(
            f"unknown WealthCoreConfig field(s) {unknown}; known: "
            f"{sorted(known)}")
    return dataclasses.replace(cfg, **dict(change))


__all__ = ["HASH_ORDER", "ParityViolation", "TunnelMode", "TunnelRun",
           "apply_config_change", "baseline_replay", "experiment",
           "first_divergence"]
