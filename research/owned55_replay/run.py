"""Passively compare owned55 against one uniformly sourced canonical Core run."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import importlib
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

from research.owned55_replay.model import (
    Owned55, digest, helper, oracle, owned55_rule, update_metrics, validate_resume,
)


class ResearchRefusal(BaseException):
    """Fail without the production runner's evidence-wait retry loop."""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("runtime", "archive", "sfp", "supplements", "output"):
        parser.add_argument("--"+name, type=Path, required=True)
    parser.add_argument("--resume", type=Path)
    parser.add_argument("--seconds", type=int, default=3600)
    parser.add_argument("--end", default="2026-07-31")
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("preserve earlier run segments")

    sys.path[:0] = [str(args.runtime.resolve()), str(args.runtime.resolve()/"shared")]
    sys.argv = ["owned55", "--harness", str(args.runtime)]
    production = importlib.import_module("research.economic_replay60.run")
    helpers, helper_sha = helper()
    Probe = helpers["ProbeController"]
    control = Probe("current")
    challenger = Owned55(Probe("current"))
    rule, parent_source_sha = owned55_rule()
    binding = dict(schema="owned55-economic-comparison/1", helper_sha256=helper_sha,
        parent_owned_source_sha256=parent_source_sha, rule=rule,
        research_sources={name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                          for name in ("run.py", "model.py")},
        supplements_sha256=hashlib.sha256(args.supplements.read_bytes()).hexdigest(),
        controller_identities=dict(current=control.identity, owned55=challenger.identity),
        end=args.end, origin="2006-01-03", measurement="2006-07-31", capital="100000")
    economics = dict(strategy_nav="100000", last_session=None,
                     pending_allocation=None, held_allocation=None)
    metrics, control_metrics, cursor, count = {}, {}, None, 0
    drift = dict(first_difference=None, max_relative_nav_difference=0., differing_decisions=0)
    if args.resume:
        pointer = json.loads(args.resume.read_text())
        raw = Path(pointer["path"]).read_bytes()
        if hashlib.sha256(raw).hexdigest() != pointer["sha256"]:
            raise ValueError("checkpoint bytes changed")
        packet = json.loads(gzip.decompress(raw))
        extra = validate_resume(packet.get("owned55_research"), binding,
                                packet["state"]["last_processed_session"])
        control.restore(extra["controllers"]["current"])
        challenger.restore(extra["controllers"]["owned55"])
        economics, metrics, control_metrics, cursor, count, drift = (
            extra[key] for key in
            ("economics", "metrics", "control_metrics", "cursor", "count", "baseline_drift"))

    retained_raw = subprocess.check_output(["git", "show",
        "7b5dda96ce4235363c5c6ded3974d3fb2970f432:audit/economic-replay-resume-430/accepted-daily.jsonl.gz"])
    retained = {row["date"]: row for row in map(json.loads, gzip.decompress(retained_raw).splitlines())}
    trace = None
    original_advance = production.EconomicPath.advance
    variant_account = production.EconomicPath(100000)
    original_checkpoint = production.write_checkpoint

    def checkpoint(output, packet):
        if packet["state"]["last_processed_session"] != cursor:
            raise ResearchRefusal("Core and owned55 checkpoint cursors differ")
        extra = dict(binding=binding,
            controllers=dict(current=control.snapshot(), owned55=challenger.snapshot()),
            economics=economics, metrics=metrics, control_metrics=control_metrics,
            cursor=cursor, count=count, baseline_drift=drift)
        extra["sha256"] = digest(extra)
        return original_checkpoint(output, {**packet, "owned55_research": extra})

    production.write_checkpoint = checkpoint
    failure = []
    original_kernel = production.advance_session

    def guarded_kernel(*args, **kwargs):
        try:
            return original_kernel(*args, **kwargs)
        except Exception as exc:
            failure.append(str(exc))
            raise

    production.advance_session = guarded_kernel
    original_supplements = production.load_supplements

    def frozen_supplements(path, applied, last_session):
        if failure:
            raise ResearchRefusal("production refused: "+failure[-1])
        if hashlib.sha256(path.read_bytes()).hexdigest() != binding["supplements_sha256"]:
            raise ResearchRefusal("supplement input changed during comparison")
        return original_supplements(path, applied, last_session)

    production.load_supplements = frozen_supplements
    original_sessions = production.JanuaryInputs.sessions

    def sessions(data, after=None):
        for day, rows in original_sessions(data, after):
            if day > args.end:
                break
            yield day, rows

    production.JanuaryInputs.sessions = sessions

    def capture(account, *, previous, state, strategy_prices):
        nonlocal economics, metrics, control_metrics, cursor, count, trace
        current_economics = original_advance(account, previous=previous, state=state,
                                             strategy_prices=strategy_prices)
        day = state.last_processed_session
        if cursor != previous["last_session"]:
            raise ResearchRefusal("owned55 transition detached from prior Core close")
        evidence, decision = state.last_evidence, state.last_decision
        row = dict(session=day, observation=evidence["observation"],
            leadership=evidence["recent_leadership"],
            core_multiplier=decision["target_core_exposure"],
            native_multiplier=decision["native_target_core_exposure"],
            recovery_reason=decision["ldrc"]["reason"],
            native_evidence=evidence["native_controller"]["evidence"])
        try:
            before_control, before_challenger = control.snapshot(), challenger.snapshot()
            current = control.step(row)
            owned = challenger.step(row)
            helpers["assert_baseline"](row, current, control)
            if owned["base"] != current:
                raise AssertionError("challenger parent differs from current controller")
            if current["fast"] != decision["evidence"]["fast_signal"] or current["slow"] != decision["evidence"]["slow_signal"]:
                raise AssertionError("current signal parity failed")
            if count % 100 == 0:
                restored_control = Probe("current")
                restored_control.restore(json.loads(json.dumps(before_control)))
                if restored_control.step(row) != current or restored_control.snapshot() != control.snapshot():
                    raise AssertionError("current controller restart differs")
                restored_owned = Owned55(Probe("current"))
                restored_owned.restore(json.loads(json.dumps(before_challenger)))
                if restored_owned.step(row) != owned or restored_owned.snapshot() != challenger.snapshot():
                    raise AssertionError("owned55 controller restart differs")
            view = SimpleNamespace(last_processed_session=day, last_evidence=evidence,
                shadow_nav_history=state.shadow_nav_history,
                last_decision={"target_core_exposure": owned["target"]})
            variant = original_advance(variant_account, previous=economics, state=view,
                                       strategy_prices=strategy_prices)
            from decimal import Decimal
            for prior, result in ((previous, current_economics), (economics, variant)):
                if abs(oracle(prior, result)-Decimal(result["strategy_nav"])) >= Decimal("1e-14"):
                    raise AssertionError("independent account oracle differs")
        except Exception as exc:
            raise ResearchRefusal("controller/accounting parity failed at "+day+": "+repr(exc)) from exc

        old = retained[day]
        difference = abs(float(current_economics["strategy_nav"])/float(old["nav"])-1)
        changed = decision != old["decision"]
        if difference > 1e-10 or changed:
            drift["first_difference"] = drift["first_difference"] or day
        drift["max_relative_nav_difference"] = max(drift["max_relative_nav_difference"], difference)
        drift["differing_decisions"] += changed
        metrics = update_metrics(metrics, day, variant["strategy_nav"])
        control_metrics = update_metrics(control_metrics, day, current_economics["strategy_nav"])
        economics, cursor, count = variant, day, count+1
        if trace is None:
            trace = (args.output/"comparison.jsonl").open("w", encoding="utf-8", newline="\n")
        trace.write(json.dumps(dict(**row, current=current, owned55=owned,
            current_economics=current_economics, owned55_economics=variant,
            baseline_drift=difference), allow_nan=False)+"\n")
        trace.flush()
        status = dict(status="RUNNING", date=day, total_sessions=count,
            control=control_metrics, owned55=metrics, baseline_drift=drift,
            targets=dict(current=current["target"], owned55=owned["target"]),
            owned_cause=dict(active=owned["active"], reason=owned["reason"],
                             entry_streak=owned["entry_streak"], recovery_streak=owned["recovery_streak"]))
        production.dump(args.output/"comparison-status.json", status)
        if count % 100 == 0:
            print("OWNED55", json.dumps(status), flush=True)
        return current_economics

    production.EconomicPath.advance = capture
    sys.argv = ["owned55", "--harness", str(args.runtime), "--archive", str(args.archive),
        "--sfp", str(args.sfp), "--supplements", str(args.supplements),
        "--output", str(args.output), "--seconds", str(args.seconds)]
    if args.resume:
        sys.argv += ["--resume", str(args.resume)]
    try:
        production.main()
    finally:
        if trace:
            trace.close()
    status = json.loads((args.output/"comparison-status.json").read_text())
    status["status"] = "COMPLETE" if cursor == args.end else "STOPPED_RESUMABLE"
    production.dump(args.output/"comparison-status.json", status)
    print("OWNED55_FINAL", json.dumps(status), flush=True)


if __name__ == "__main__":
    main()
