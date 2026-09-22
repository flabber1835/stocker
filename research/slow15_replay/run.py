"""Passively compare slow15 against one uniformly sourced canonical Core run."""
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

from research.slow15_replay.model import digest, helper, oracle, update_metrics, validate_resume


class ResearchRefusal(BaseException):
    """Fail the worker without the original runner's evidence-wait retry loop."""


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
    sys.argv = ["slow15", "--harness", str(args.runtime)]
    run = importlib.import_module("research.economic_replay60.run")
    helpers, helper_sha = helper()
    Probe = helpers["ProbeController"]
    probes = {name: Probe(name) for name in ("current", "slow_earlier")}
    binding = dict(schema="slow15-economic-comparison/1", helper_sha256=helper_sha,
        research_sources={name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                          for name in ("run.py", "model.py")},
        supplements_sha256=hashlib.sha256(args.supplements.read_bytes()).hexdigest(),
        controller_identities={name: p.identity for name, p in probes.items()},
        end=args.end, origin="2006-01-03", measurement="2006-07-31", capital="100000")
    economics = dict(strategy_nav="100000", last_session=None, pending_allocation=None, held_allocation=None)
    metrics, control_metrics, cursor, count = {}, {}, None, 0
    drift = dict(first_difference=None, max_relative_nav_difference=0., differing_decisions=0)
    if args.resume:
        pointer = json.loads(args.resume.read_text())
        raw = Path(pointer["path"]).read_bytes()
        if hashlib.sha256(raw).hexdigest() != pointer["sha256"]:
            raise ValueError("checkpoint bytes changed")
        packet = json.loads(gzip.decompress(raw))
        extra = validate_resume(packet.get("slow15_research"), binding, packet["state"]["last_processed_session"])
        for name, probe in probes.items():
            probe.restore(extra["controllers"][name])
        economics, metrics, control_metrics, cursor, count, drift = (
            extra[k] for k in ("economics", "metrics", "control_metrics", "cursor", "count", "baseline_drift"))
    retained_raw = subprocess.check_output(["git", "show", "7b5dda96ce4235363c5c6ded3974d3fb2970f432:audit/economic-replay-resume-430/accepted-daily.jsonl.gz"])
    retained = {r["date"]: r for r in map(json.loads, gzip.decompress(retained_raw).splitlines())}
    # The production runner creates output itself. Place sidecars outside that
    # directory until its source/input validation succeeds and it creates it.
    trace = None
    original_advance = run.EconomicPath.advance
    variant_account = run.EconomicPath(100000)
    original_checkpoint = run.write_checkpoint
    def checkpoint(output, packet):
        if packet["state"]["last_processed_session"] != cursor:
            raise ResearchRefusal("Core and research checkpoint cursors differ")
        extra = dict(binding=binding, controllers={n: p.snapshot() for n, p in probes.items()},
            economics=economics, metrics=metrics, control_metrics=control_metrics,
            cursor=cursor, count=count, baseline_drift=drift)
        extra["sha256"] = digest(extra)
        return original_checkpoint(output, {**packet, "slow15_research": extra})
    run.write_checkpoint = checkpoint
    failure = []
    original_kernel = run.advance_session
    def guarded_kernel(*a, **kw):
        try:
            return original_kernel(*a, **kw)
        except Exception as exc:
            failure.append(str(exc))
            raise
    run.advance_session = guarded_kernel
    original_supplements = run.load_supplements
    def frozen_supplements(path, applied, last_session):
        if failure:
            raise ResearchRefusal("production refused: "+failure[-1])
        if hashlib.sha256(path.read_bytes()).hexdigest() != binding["supplements_sha256"]:
            raise ResearchRefusal("supplement input changed during comparison")
        return original_supplements(path, applied, last_session)
    run.load_supplements = frozen_supplements
    original_sessions = run.JanuaryInputs.sessions
    def sessions(data, after=None):
        for day, rows in original_sessions(data, after):
            if day > args.end:
                break
            yield day, rows
    run.JanuaryInputs.sessions = sessions
    def capture(account, *, previous, state, strategy_prices):
        nonlocal economics, metrics, control_metrics, cursor, count, trace
        current = original_advance(account, previous=previous, state=state, strategy_prices=strategy_prices)
        day = state.last_processed_session
        if cursor != previous["last_session"]:
            raise ResearchRefusal("research transition detached from prior Core close")
        evidence, decision = state.last_evidence, state.last_decision
        row = dict(session=day, observation=evidence["observation"], leadership=evidence["recent_leadership"],
            core_multiplier=decision["target_core_exposure"], native_multiplier=decision["native_target_core_exposure"],
            recovery_reason=decision["ldrc"]["reason"], native_evidence=evidence["native_controller"]["evidence"])
        try:
            before = {n: p.snapshot() for n, p in probes.items()}
            results = {n: p.step(row) for n, p in probes.items()}
            helpers["assert_baseline"](row, results["current"], probes["current"])
            assert results["current"]["fast"] == decision["evidence"]["fast_signal"]
            assert results["current"]["slow"] == decision["evidence"]["slow_signal"]
            if count % 100 == 0:
                for name, probe in probes.items():
                    restored = Probe(name)
                    restored.restore(json.loads(json.dumps(before[name])))
                    assert restored.step(row) == results[name]
                    assert restored.snapshot() == probe.snapshot()
            view = SimpleNamespace(last_processed_session=day, last_evidence=evidence,
                shadow_nav_history=state.shadow_nav_history,
                last_decision={"target_core_exposure": results["slow_earlier"]["target"]})
            variant = original_advance(variant_account, previous=economics, state=view, strategy_prices=strategy_prices)
            from decimal import Decimal
            for prior, result in ((previous, current), (economics, variant)):
                assert abs(oracle(prior, result)-Decimal(result["strategy_nav"])) < Decimal('1e-14')
        except Exception as exc:
            raise ResearchRefusal("controller/accounting parity failed at "+day+": "+repr(exc)) from exc
        old = retained[day]
        difference = abs(float(current["strategy_nav"])/float(old["nav"])-1)
        changed = decision != old["decision"]
        if difference > 1e-10 or changed:
            drift["first_difference"] = drift["first_difference"] or day
        drift["max_relative_nav_difference"] = max(drift["max_relative_nav_difference"], difference)
        drift["differing_decisions"] += changed
        metrics = update_metrics(metrics, day, variant["strategy_nav"])
        control_metrics = update_metrics(control_metrics, day, current["strategy_nav"])
        economics, cursor, count = variant, day, count+1
        if trace is None:
            trace = (args.output/"comparison.jsonl").open("w", encoding="utf-8", newline="\n")
        trace.write(json.dumps(dict(**row, results=results, current_economics=current,
            slow15_economics=variant, baseline_drift=difference), allow_nan=False)+"\n")
        trace.flush()
        status = dict(status="RUNNING", date=day, total_sessions=count,
            control=control_metrics, slow15=metrics, baseline_drift=drift,
            targets={n:r["target"] for n,r in results.items()})
        run.dump(args.output/"comparison-status.json", status)
        if count % 100 == 0:
            print("SLOW15", json.dumps(status), flush=True)
        return current
    run.EconomicPath.advance = capture
    sys.argv = ["slow15", "--harness", str(args.runtime), "--archive", str(args.archive),
        "--sfp", str(args.sfp), "--supplements", str(args.supplements), "--output", str(args.output),
        "--seconds", str(args.seconds)]
    if args.resume:
        sys.argv += ["--resume", str(args.resume)]
    try:
        run.main()
    finally:
        if trace:
            trace.close()
    status = json.loads((args.output/"comparison-status.json").read_text())
    status["status"] = "COMPLETE" if cursor == args.end else "STOPPED_RESUMABLE"
    run.dump(args.output/"comparison-status.json", status)
    print("SLOW15_FINAL", json.dumps(status), flush=True)


if __name__ == "__main__":
    main()
