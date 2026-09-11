"""Read-only comparator for the independently retained PR352 certification."""
from __future__ import annotations

import csv
import gzip
import json
import math
from pathlib import Path
from collections import defaultdict

from . import authority as a
from .evidence import Divergence, require


def load(path):
    with gzip.open(path, "rt", newline="") as source:
        rows = list(csv.DictReader(source))
    result = {r["date"]: r for r in rows}
    require("reference_unique_dates", len(rows), len(result))
    return result


def grouped_rows(path, date_key="date"):
    result=defaultdict(list)
    with gzip.open(path,"rt",newline="") as source:
        for row in csv.DictReader(source):
            result[row[date_key]].append(row)
    return dict(result)


def compare_composition(expected, state, nav, effective, desired):
    positions={}
    for episode in state.wealth_core["episodes"].values():
        sid=episode["security_id"]
        row=positions.setdefault(sid,dict(quantity=0.,lot_count=0,ticker=episode["ticker"]))
        require("position_lot_ticker:"+sid,row["ticker"],episode["ticker"])
        row["quantity"]+=episode["current_shares"]
        row["lot_count"]+=1
    wanted={row["security_id"]:row for row in expected if row["bucket"]=="STOCK"}
    require("composition_security_keys",sorted(wanted),sorted(positions))
    values={"CORE_CASH":state.wealth_core["cash"],"TBILL_SLEEVE":0.,
            "DIVIDEND_RECEIVABLE":sum(float(r["amount"]) for r in state.ledger["receivables"])}
    for sid,actual in positions.items():
        mark=float(state.last_known[sid])
        actual.update(mark=mark,reference_value=actual["quantity"]*mark)
        for name in ("quantity","mark","reference_value"):
            equal("position:"+sid+":"+name,wanted[sid][name],actual[name],money=name=="reference_value")
        require("position_ticker:"+sid,wanted[sid]["ticker"],actual["ticker"])
        require("position_lots:"+sid,int(wanted[sid]["lot_count"]),actual["lot_count"])
    for row in expected:
        bucket=row["bucket"]
        value=positions[row["security_id"]]["reference_value"] if bucket=="STOCK" else values[bucket]
        label=row["security_id"] or bucket
        equal("composition_value:"+label,row["reference_value"],value,money=True)
        weight=100*value/nav
        for field,actual in (("shadow_weight_pct",weight),
            ("effective_model_weight_pct",100*(1-effective) if bucket=="TBILL_SLEEVE" else weight*effective),
            ("next_target_model_weight_pct",100*(1-desired) if bucket=="TBILL_SLEEVE" else weight*desired)):
            equal(field+":"+label,row[field],actual)
    equal("composition_conservation",nav,sum(p["reference_value"] for p in positions.values())+sum(values.values()),money=True)
    return positions,values


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
        self.composition=grouped_rows(root / "portfolio-composition.csv.gz")
        self.entries=grouped_rows(root / "core/engine/close-decisions.csv.gz","decision_date")
        self.result = json.loads((root / "RESULT.json").read_text())
        require("reference_status", "PASS_RESEARCH_CHAMPION_CERTIFICATION", self.result["status"])
        require("reference_source", a.CHAMPION_SHA256, self.result["source_sha256"])
        require("reference_dataset", a.DATASET_SHA256, self.result["dataset_sha256"])
        require("reference_observations", a.OBSERVATIONS, len(self.observations))
        require("reference_measured", a.MEASURED, len(self.daily))
        require("reference_composition_dates", set(self.observations), set(self.portfolio))
        require("reference_position_dates",set(self.observations),set(self.composition))
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
        held = sorted(ep["security_id"] for ep in state.wealth_core["episodes"].values())
        require("held_securities", sorted(json.loads(portfolio["held_ids_json"])), held)
        equal("core_cash", portfolio["cash"], state.wealth_core["cash"], money=True)
        positions,values=compare_composition(self.composition[day],state,nav,self.pending,
                                           decision["target_core_exposure"])
        equal("core_receivables",portfolio["receivables"],values["DIVIDEND_RECEIVABLE"],money=True)
        entries=[r for r in self.entries.get(day,()) if r["outcome"]=="PLAN_OPEN_SIZE"]
        actual_entries=[p for p in state.pending if p["signal_session"]==day
                        and p["operation"]=="OPEN_SLOT_POSITION"]
        require("admission_order",[p["ticker"] for p in entries],[p["ticker"] for p in actual_entries])
        for expected_entry,actual_entry in zip(entries,actual_entries):
            equal("admission_dollars:"+actual_entry["security_id"],expected_entry["intended_capital"],
                  actual_entry["intended_dollars"],money=True)
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
            allocation=self.allocation, next_target=self.pending, held=held,
            positions=positions,cash_buckets=values,admissions=actual_entries)

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
