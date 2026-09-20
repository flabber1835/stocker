"""Bounded controller comparison against independently retained dated decisions."""
from __future__ import annotations

import argparse
import csv
from decimal import Decimal, localcontext
import hashlib
import json
from pathlib import Path
import time

from sentinel.controller import champion_config, median5
from sentinel.controller.machine import Controller, Observation
from sentinel.strategy import production_strategy
from stock_strategy_shared.wealth_core import v5
from .run import verify_production, dump

OBSERVATIONS_SHA = "87b54e24c1c1267f788cadd8d5043e426b4c4354b757a498a3c3a13b3afe7def"
DAILY_SHA = "cda954a33aa4e16d72a8124219ae9eb7f526f003d0c8b4f5dbb88c69e498caeb"
FIELDS = dict(shadow_nav="nav", shadow_drawdown="dd", shadow_r5="r5",
    shadow_r10="r10", shadow_r20="r20", shadow_r40="r40",
    damaged_breadth="dam", green_breadth="green", damaged_breadth_delta5="ddam5",
    spy_r20="spy20", spy_vol_ratio="volacc")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rows(path):
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def number(value):
    return float(value) if value else None


def replay(observations, *, restore=False):
    cfg, _ = production_strategy()
    controller = Controller(cfg)
    native, recovery = controller.initial_state(), median5.fresh(champion=True)
    actual = []
    for index, row in enumerate(observations):
        ob = Observation(session=row["date"], stops20=int(row["stops20"]),
            **{field: number(row[column]) for field, column in FIELDS.items()})
        allocation = recovery["previous_desired"]
        effective = recovery["previous_native"]
        preclose = recovery["effective_native"]
        native, decision = controller.step(observation=ob, state=native)
        recovery, result = champion_config.recover(state=recovery,
            native=decision.target_core_exposure, wc_drawdown=ob.shadow_drawdown,
            recent_r20=number(row["recent_r20"]), recent_r40=number(row["recent_r40"]),
            spy_r20=ob.spy_r20, wc_r20=ob.shadow_r20)
        actual.append(dict(date=ob.session, allocation=allocation,
            native_close_target=decision.target_core_exposure, effective_native=effective,
            effective_native_preclose=preclose, close_desired=result["desired_allocation"],
            close_reason=result["reason"], fast_signal=decision.evidence["fast_signal"],
            slow_signal=decision.evidence["slow_signal"]))
        if restore and (index + 1) % 300 == 0:
            native, recovery = json.loads(json.dumps([native, recovery], allow_nan=False))
    return actual


def differences(actual, expected, fields):
    if [r["date"] for r in actual] != [r["date"] for r in expected]:
        raise ValueError("comparison dates differ, duplicate or missing rows are not skipped")
    return [dict(date=a["date"], field=field, actual=a[field], expected=e[field])
            for a, e in zip(actual, expected) for field in fields if a[field] != e[field]]


def sizing_smoke(reference):
    failures, budgets, openings = [], [], []
    admissions = rows(reference / "core/engine/close-decisions.csv")
    for r in admissions:
        intended, reason = v5.admission(equity=float(r["close_nav"]),
            cash=float(r["cash_before_decision"]), price=float(r["close_price"]))
        outcome = "PLAN_OPEN_SIZE" if intended is not None else "Q0_SKIP"
        if outcome != r["outcome"] or (intended is None and reason != r["q0_reason"]):
            failures.append(dict(date=r["decision_date"], ticker=r["ticker"],
                actual=outcome, expected=r["outcome"], reason=reason))
        if intended is not None and intended != float(r["intended_capital"]):
            budgets.append(dict(date=r["decision_date"], ticker=r["ticker"],
                actual=intended, expected=float(r["intended_capital"])))
    for r in rows(reference / "core/engine/open-sizing-events.csv"):
        if r["mode"] != "whole":
            raise ValueError("unexpected retained sizing mode")
        quantity = v5.opening_quantity(intended=float(r["intended_target_dollars"]),
            cash=float(r["cash_before_execution"]), price=float(r["open_price"]))
        with localcontext() as ctx:
            ctx.prec = 80
            limit = min(Decimal(r["intended_target_dollars"]), Decimal(r["cash_before_execution"]))
            cost = Decimal(r["open_price"]) * Decimal("1.001")
            bounds_pass = quantity * cost <= limit < (quantity + 1) * cost
            oversized_rejected = not ((quantity + 1) * cost <= limit)
        if not bounds_pass or not oversized_rejected:
            raise ValueError("opening quantity violates independent cost bounds")
        record = dict(date=r["execution_date"], decision_date=r["decision_date"], ticker=r["ticker"],
                      actual=quantity, expected=float(r["executed_shares"]))
        openings.append(record)
        if quantity != record["expected"]:
            failures.append(record)
    return dict(admission_cases=len(admissions), opening_cases=len(openings),
        decision_mismatches=len(failures), budget_numeric_differences=len(budgets),
        largest_budget_difference=max((abs(r["actual"]-r["expected"]) for r in budgets), default=0),
        independent_opening_bounds="PASS", oversized_quantity_falsifier="PASS"), failures, budgets, openings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    started = time.monotonic()
    root = Path(__file__).resolve().parents[2]
    manifest = json.loads(Path(__file__).with_name("production-source.json").read_text(encoding="utf-8"))
    verify_production(root, manifest)
    checksums = json.loads((args.reference / "SHA256.json").read_text(encoding="utf-8"))
    for name, expected in checksums.items():
        if digest(args.reference / name) != expected:
            raise ValueError("retained artifact bytes differ: " + name)
    if digest(args.reference / "observations.csv") != OBSERVATIONS_SHA:
        raise ValueError("retained observation identity differs")
    if digest(args.reference / "champion-daily.csv") != DAILY_SHA:
        raise ValueError("retained decision identity differs")
    if (args.reference / "RESULT.json").read_bytes() != (root / "tests/champion/certified_result.json").read_bytes():
        raise ValueError("retained result differs from repository reference")
    observations = rows(args.reference / "observations.csv")
    if len(observations) != 5176 or len({r["date"] for r in observations}) != 5176:
        raise ValueError("retained observation coverage differs")
    actual = replay(observations)
    restored = replay(observations, restore=True)
    expected = [dict(date=r["date"],
        native_close_target=float(r["current_native_close_target"]),
        effective_native_preclose=float(r["current_effective_native_preclose"]),
        close_desired=float(r["current_close_desired"]), close_reason=r["current_close_reason"])
        for r in observations]
    failures = differences(actual, expected, ("native_close_target", "effective_native_preclose", "close_desired", "close_reason"))
    measured = [a for a, r in zip(actual, observations) if r["measured"] == "True"]
    daily = [dict(date=r["date"], **{k: float(r[k]) for k in (
        "allocation", "native_close_target", "effective_native", "close_desired")},
        close_reason=r["close_reason"], fast_signal=r["fast_signal"] == "True",
        slow_signal=r["slow_signal"] == "True") for r in rows(args.reference / "champion-daily.csv")]
    failures += differences(measured, daily, tuple(k for k in daily[0] if k != "date"))
    restoration_failures = differences(actual, restored, tuple(k for k in actual[0] if k != "date"))
    # Falsifier: an intentionally wrong exposure in expected evidence must be detected.
    broken = [dict(r) for r in daily]
    broken[0]["close_desired"] = 1.0 - broken[0]["close_desired"]
    falsifier = differences(measured, broken, ("close_desired",))
    falsifier_detected = any(d["date"] == daily[0]["date"] and d["field"] == "close_desired" for d in falsifier)
    if not falsifier_detected:
        raise ValueError("comparison falsifier was not detected")
    transitions = [dict(r, prior_allocation=measured[i-1]["allocation"])
                   for i, r in enumerate(measured) if i and r["allocation"] != measured[i-1]["allocation"]]
    sizing, sizing_failures, budgets, openings = sizing_smoke(args.reference)
    result = dict(status="PASS_CONDITIONAL_DECISION_SMOKE" if not failures and not restoration_failures and not sizing_failures else "FAIL",
        production_revision=manifest["revision"], reference_run="34544522249",
        observations=len(observations), measured_sessions=len(measured),
        first_date=measured[0]["date"], last_date=measured[-1]["date"],
        comparison_mismatches=len(failures), restart_mismatches=len(restoration_failures),
        restart_checkpoints=len(observations)//300, comparator_falsifier_detected=falsifier_detected,
        exposure_transitions=len(transitions), elapsed_seconds=time.monotonic()-started,
        sizing=sizing,
        reference_metrics=json.loads((args.reference / "RESULT.json").read_text(encoding="utf-8"))["metrics"]["20"],
        source_hashes=dict(observations=OBSERVATIONS_SHA, decisions=DAILY_SHA,
                           script=digest(Path(__file__))),
        scope="Current controller, admissions and sizing on retained inputs; no ranking, upstream-input, return or full-system parity claim")
    args.output.mkdir(parents=True, exist_ok=False)
    dump(args.output / "result.json", result)
    dump(args.output / "mismatches.json", failures + restoration_failures)
    dump(args.output / "exposure-transitions.json", transitions)
    dump(args.output / "sizing-mismatches.json", sizing_failures)
    dump(args.output / "budget-differences.json", budgets)
    dump(args.output / "opening-quantities.json", openings)
    with (args.output / "decisions.jsonl").open("w", encoding="utf-8") as stream:
        for row in actual:
            stream.write(json.dumps(row, sort_keys=True, allow_nan=False) + "\n")
    print(json.dumps(result, indent=2), flush=True)
    return int(result["status"] == "FAIL")


if __name__ == "__main__":
    raise SystemExit(main())
