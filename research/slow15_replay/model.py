"""Research state bindings and independent dollar-fraction accounting."""
from datetime import date
from decimal import Decimal
import hashlib
import json
import math
import subprocess

HELPER_COMMIT = "f2a50c7b6ff4c9686f49b6eb53863e8e2b9959bb"
HELPER_PATH = "research/impedance/parameters.py"
START = "2006-07-31"


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def helper():
    raw = subprocess.check_output(["git", "show", f"{HELPER_COMMIT}:{HELPER_PATH}"])
    namespace = {"__name__": "frozen_slow15_research_helper"}
    exec(compile(raw, HELPER_PATH, "exec"), namespace)
    assert namespace["PRESETS"]["slow_earlier"] == {"SLOW": {"dur": 15}}
    return namespace, hashlib.sha256(raw).hexdigest()


def oracle(previous, result):
    """Independent money arithmetic; use prior decisions, never today's signal."""
    D = Decimal
    prior_nav = D(previous["strategy_nav"])
    if previous["last_session"] is None:
        return prior_nav
    new = D(str(previous["pending_allocation"]))
    opening, closing = (D(result[k]) for k in ("parent_core_open_equity", "parent_core_close_equity"))
    bill_open, bill_close, bill_previous = (D(result[k]) for k in
        ("bil_open_adjusted", "bil_close_adjusted", "bil_previous_close_adjusted_current_publication"))
    if previous["held_allocation"] is None:
        after_cost = prior_nav*(1-D('.001')*(1-new))
        return after_cost*new*closing/opening + after_cost*(1-new)*bill_close/bill_open
    old = D(str(previous["held_allocation"]))
    prior_core = D(previous["parent_core_close_equity"])
    if new == old:
        return prior_nav*old*closing/prior_core + prior_nav*(1-old)*bill_close/bill_previous
    open_nav = prior_nav*old*opening/prior_core + prior_nav*(1-old)*bill_open/bill_previous
    after_cost = open_nav*(1-D('.001')*abs(new-old))
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
        raise ValueError("research source/input binding changed")
    if extra.get("cursor") != cursor or extra["economics"]["last_session"] != cursor:
        raise ValueError("research cursor differs from Core checkpoint")
    expected = digest({k: v for k, v in extra.items() if k != "sha256"})
    if extra.get("sha256") != expected:
        raise ValueError("research checkpoint commitment changed")
    return extra
