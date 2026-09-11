"""Read-only comparator for the independently retained PR352 certification."""
from __future__ import annotations

import csv
import gzip
import json
import math
from pathlib import Path

from . import authority as a
from .evidence import Divergence, require


def load(path):
    with gzip.open(path, "rt", newline="") as source:
        rows = list(csv.DictReader(source))
    result = {r["date"]: r for r in rows}
    require("reference_unique_dates", len(rows), len(result))
    return result


def equal(name, expected, actual, *, money=False):
    if expected == "" or expected is None:
        if actual is None or (isinstance(actual, float) and math.isnan(actual)):
            return
        raise Divergence(name, expected, actual)
    expected, actual = float(expected), float(actual)
    if not math.isclose(expected, actual, rel_tol=1e-12, abs_tol=1e-4 if money else 1e-12):
        raise Divergence(name, expected, actual)


class Comparison:
    def __init__(self, root):
        self.observations = load(root / "observations.csv.gz")
        self.portfolio = load(root / "portfolio-sessions.csv.gz")
        self.daily = load(root / "champion-daily.csv.gz")
        self.result = json.loads((root / "RESULT.json").read_text())
        require("reference_status", "PASS_RESEARCH_CHAMPION_CERTIFICATION", self.result["status"])
        require("reference_source", a.CHAMPION_SHA256, self.result["source_sha256"])
        require("reference_dataset", a.DATASET_SHA256, self.result["dataset_sha256"])
        require("reference_observations", a.OBSERVATIONS, len(self.observations))
        require("reference_measured", a.MEASURED, len(self.daily))
        require("reference_composition_dates", set(self.observations), set(self.portfolio))
        self.previous_equity, self.allocation, self.pending, self.nav = None, 1., 1., 1.
        self.processed, self.measured = [], []

    def observe(self, day, state, opened, cash_factors):
        expected, portfolio = self.observations[day], self.portfolio[day]
        evidence, decision = state.last_evidence, state.last_decision
        ob = evidence["observation"]
        fields = {"dd":"shadow_drawdown", "r5":"shadow_r5", "r10":"shadow_r10", "r20":"shadow_r20",
            "r40":"shadow_r40", "dam":"damaged_breadth", "green":"green_breadth",
            "ddam5":"damaged_breadth_delta5", "spy20":"spy_r20", "volacc":"spy_vol_ratio", "stops20":"stops20"}
        for target, source in fields.items():
            equal("observation:"+target, expected[target], ob[source])
        nav = ob["shadow_nav"]
        equal("shadow_nav", expected["nav"], nav, money=True)
        equal("opening_equity", expected["open_eq"], opened, money=True)
        equal("native_target", expected["current_native_close_target"], decision["native_target_core_exposure"])
        equal("close_target", expected["current_close_desired"], decision["target_core_exposure"])
        require("recovery_reason", expected["current_close_reason"], decision["ldrc"]["reason"])
        held = sorted({ep["security_id"] for ep in state.wealth_core["episodes"].values()})
        require("held_securities", sorted(json.loads(portfolio["held_ids_json"])), held)
        equal("core_cash", portfolio["cash"], state.wealth_core["cash"], money=True)
        if day >= a.MEASUREMENT:
            if self.previous_equity is not None:
                gap, intraday = cash_factors
                old, new = self.allocation, self.pending
                if old == new:
                    factor = old*nav/self.previous_equity + (1-old)*gap*intraday
                else:
                    factor = 1+old*(opened/self.previous_equity-1)+(1-old)*(gap-1)
                    factor *= 1-.001*abs(new-old)
                    factor *= 1+new*(nav/opened-1)+(1-new)*(intraday-1)
                self.nav *= factor
            self.allocation = self.pending
            equal("effective_allocation", self.daily[day]["allocation"], self.allocation)
            equal("scalar_nav", self.daily[day]["nav"], self.nav)
            self.previous_equity = nav
            self.measured.append(day)
        self.pending = decision["target_core_exposure"]
        self.processed.append(day)
        return dict(shadow_nav=nav, opening_equity=opened, scalar_nav=self.nav,
            allocation=self.allocation, next_target=self.pending, held=held)

    def finish(self):
        require("full_observation_schedule", sorted(self.observations), self.processed)
        require("full_measured_schedule", sorted(self.daily), self.measured)
        target = self.result["metrics"]["20"]
        equal("ending_multiple", target["ending_multiple"], self.nav)
        # Certification uses calendar years in this exactly twenty-year window.
        years = ( __import__("datetime").date.fromisoformat(a.END)
                 - __import__("datetime").date.fromisoformat(a.MEASUREMENT)).days/365.25
        cagr = self.nav**(1/years)-1
        equal("cagr", target["cagr"], cagr)
        return dict(cagr=cagr, ending_multiple=self.nav, observations=len(self.processed),
                    measured=len(self.measured))
