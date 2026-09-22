"""Frozen owned55 policy, state binding, and independent money arithmetic."""
from __future__ import annotations

import ast
from datetime import date
from decimal import Decimal
import hashlib
import json
import math
import subprocess

PARENT_COMMIT = "7250ce3d65cc38a103989d460fe3c557a38343c8"
PARENT_PATH = "sentinel/controller/owned_impairment.py"
HELPER_COMMIT = "f2a50c7b6ff4c9686f49b6eb53863e8e2b9959bb"
HELPER_PATH = "research/impedance/parameters.py"
START = "2006-07-31"


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _git_source(commit, path):
    return subprocess.check_output(["git", "show", f"{commit}:{path}"])


def parent_rule():
    raw = _git_source(PARENT_COMMIT, PARENT_PATH)
    tree = ast.parse(raw, PARENT_PATH)
    assignments = [node for node in tree.body if isinstance(node, ast.Assign)
                   and any(isinstance(target, ast.Name) and target.id == "RULE" for target in node.targets)]
    if len(assignments) != 1:
        raise ValueError("owned impairment RULE is not uniquely defined")
    value = assignments[0].value
    if not (isinstance(value, ast.Call) and isinstance(value.func, ast.Name)
            and value.func.id == "dict" and not value.args):
        raise ValueError("owned impairment RULE is not a literal dict call")
    rule = {keyword.arg: ast.literal_eval(keyword.value) for keyword in value.keywords}
    if None in rule:
        raise ValueError("owned impairment RULE cannot expand dynamic values")
    return rule, hashlib.sha256(raw).hexdigest()


def helper():
    raw = _git_source(HELPER_COMMIT, HELPER_PATH)
    namespace = {"__name__": "frozen_owned55_parent_controller"}
    exec(compile(raw, HELPER_PATH, "exec"), namespace)
    return namespace, hashlib.sha256(raw).hexdigest()


def owned55_rule():
    parent, source_sha = parent_rule()
    rule = dict(parent, active_ceiling=.55)
    differences = {key for key in rule if rule[key] != parent[key]}
    if differences != {"active_ceiling"} or parent["active_ceiling"] != 0.:
        raise ValueError("owned55 must change only the parent active ceiling")
    return rule, source_sha


class Owned55:
    """Research adapter for PR #432 with only its active ceiling changed."""

    def __init__(self, base):
        self.base = base
        self.rule, self.parent_source_sha = owned55_rule()
        self.active = False
        self.entry_streak = 0
        self.recovery_streak = 0
        self.last_session = None
        self.identity = digest(dict(schema="owned55-research/1", parent_source=self.parent_source_sha,
            parent_rule=parent_rule()[0], rule=self.rule, base=base.identity))

    @staticmethod
    def _finite(value):
        return type(value) in (int, float) and math.isfinite(value)

    def step(self, row):
        day = row["session"]
        if date.fromisoformat(day).isoformat() != day or (self.last_session is not None and day <= self.last_session):
            raise ValueError("owned55 sessions must advance strictly once")
        base = self.base.step(row)
        ob, rule = row["observation"], self.rule
        dd, damage, green, r20 = (ob[key] for key in
            ("shadow_drawdown", "damaged_breadth", "green_breadth", "shadow_r20"))
        impaired = (all(self._finite(value) for value in (dd, damage, green))
                    and dd <= rule["entry_drawdown"] and damage >= rule["entry_damage"]
                    and green <= rule["entry_green"])
        healthy = (all(self._finite(value) for value in (r20, damage, green))
                   and r20 > rule["recovery_core_r20_above"]
                   and damage <= rule["recovery_damage"] and green >= rule["recovery_green"])
        reason = "OWNED_NORMAL"
        if self.active:
            self.entry_streak = 0
            self.recovery_streak = self.recovery_streak + 1 if healthy else 0
            if self.recovery_streak >= rule["recovery_sessions"]:
                self.active, self.recovery_streak, reason = False, 0, "OWNED_RECOVERED"
            else:
                reason = "OWNED_IMPAIRMENT_HELD"
        else:
            self.recovery_streak = 0
            self.entry_streak = self.entry_streak + 1 if impaired else 0
            if self.entry_streak >= rule["entry_sessions"]:
                self.active, self.entry_streak, reason = True, 0, "OWNED_IMPAIRMENT_ENTER"
        self.last_session = day
        ceiling = rule["active_ceiling"] if self.active else 1.
        return dict(base=base, native=base["native"], target=min(base["target"], ceiling),
            fast=base["fast"], slow=base["slow"], reason=reason, active=self.active,
            impaired=bool(impaired), healthy=bool(healthy), ceiling=ceiling,
            entry_streak=self.entry_streak, recovery_streak=self.recovery_streak)

    def snapshot(self):
        value = dict(identity=self.identity, base=self.base.snapshot(), active=self.active,
            entry_streak=self.entry_streak, recovery_streak=self.recovery_streak,
            last_session=self.last_session)
        value["sha256"] = digest(value)
        return value

    def restore(self, value):
        if not isinstance(value, dict) or value.get("identity") != self.identity:
            raise ValueError("owned55 identity mismatch")
        if value.get("sha256") != digest({key: item for key, item in value.items() if key != "sha256"}):
            raise ValueError("owned55 state commitment changed")
        active, entry, recovery, day = (value[key] for key in
            ("active", "entry_streak", "recovery_streak", "last_session"))
        if type(active) is not bool or type(entry) is not int or type(recovery) is not int:
            raise ValueError("owned55 state types invalid")
        if entry < 0 or entry >= self.rule["entry_sessions"] or recovery < 0 or recovery >= self.rule["recovery_sessions"]:
            raise ValueError("owned55 state counter invalid")
        if (active and entry) or (not active and recovery):
            raise ValueError("owned55 state contradicts latch")
        if day is not None and date.fromisoformat(day).isoformat() != day:
            raise ValueError("owned55 state session invalid")
        self.base.restore(value["base"])
        self.active, self.entry_streak, self.recovery_streak, self.last_session = active, entry, recovery, day


def oracle(previous, result):
    """Independent accounting: old ownership bears overnight return."""
    D = Decimal
    prior_nav = D(previous["strategy_nav"])
    if previous["last_session"] is None:
        return prior_nav
    new = D(str(previous["pending_allocation"]))
    opening, closing = (D(result[key]) for key in ("parent_core_open_equity", "parent_core_close_equity"))
    bill_open, bill_close, bill_previous = (D(result[key]) for key in
        ("bil_open_adjusted", "bil_close_adjusted", "bil_previous_close_adjusted_current_publication"))
    if previous["held_allocation"] is None:
        after_cost = prior_nav * (1-D(".001")*(1-new))
        return after_cost*new*closing/opening + after_cost*(1-new)*bill_close/bill_open
    old = D(str(previous["held_allocation"]))
    prior_core = D(previous["parent_core_close_equity"])
    if new == old:
        return prior_nav*old*closing/prior_core + prior_nav*(1-old)*bill_close/bill_previous
    open_nav = prior_nav*old*opening/prior_core + prior_nav*(1-old)*bill_open/bill_previous
    after_cost = open_nav * (1-D(".001")*abs(new-old))
    return after_cost*new*closing/opening + after_cost*(1-new)*bill_close/bill_open


def update_metrics(previous, day, value):
    if day < START:
        return dict(previous)
    value = Decimal(value)
    if not previous:
        if day != START:
            raise ValueError("measurement baseline missing")
        previous = dict(base=str(value), peak=str(value), drawdown="0", sessions=0)
    result = dict(previous)
    result["peak"] = str(max(value, Decimal(result["peak"])))
    result["drawdown"] = str(min(Decimal(result["drawdown"]), value/Decimal(result["peak"])-1))
    result["sessions"] += 1
    multiple = value/Decimal(result["base"])
    days = (date.fromisoformat(day)-date.fromisoformat(START)).days
    result.update(multiple=str(multiple), cagr=math.expm1(math.log(float(multiple))*365.2425/days) if days else None)
    return result


def validate_resume(extra, binding, cursor):
    if not isinstance(extra, dict) or extra.get("binding") != binding:
        raise ValueError("owned55 source/input binding changed")
    if extra.get("cursor") != cursor or extra["economics"]["last_session"] != cursor:
        raise ValueError("owned55 cursor differs from Core checkpoint")
    if extra.get("sha256") != digest({key: value for key, value in extra.items() if key != "sha256"}):
        raise ValueError("owned55 checkpoint commitment changed")
    return extra
