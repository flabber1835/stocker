"""Fresh bounded formation using a separately pinned, read-only production checkout."""
from __future__ import annotations

import argparse
from decimal import Decimal
import importlib.metadata
import json
from pathlib import Path
import sys
import time
import traceback

from .classifier import Classifier, FORMATION_END, POSITIVE_HASH, MANUAL_HASH


def dump(path, data):
    path.write_text(json.dumps(data, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    for name in ("harness", "archive", "sfp", "sources", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--seconds", type=int, default=1800)
    parser.add_argument("--modes", nargs="+", choices=("control", "dates", "seven", "combined"),
                        default=["control", "dates", "seven", "combined"])
    args = parser.parse_args()
    if not 0 < args.seconds <= 1800 or len(set(args.modes)) != len(args.modes):
        raise ValueError("invalid bounded experiment")
    started = time.monotonic()
    deadline = started + args.seconds
    output = args.output.resolve()
    for protected in (args.harness.resolve(), args.sources.resolve()):
        if output == protected or protected in output.parents:
            raise ValueError("output would enter protected source directory")
    output.mkdir(parents=True, exist_ok=False)
    # Import the unchanged production kernel; do not copy or patch its functions.
    sys.path[:0] = [str(args.harness.resolve()), str(args.harness.resolve() / "shared")]
    from research.bounded_20y import january as j
    from research.bounded_20y.run import metadata, vendor, number, terminals, distributions
    manifest = json.loads((args.harness / "research/bounded_20y/production-source.json").read_text())
    j.verify_production(args.harness, manifest)
    config, identity = j.production_strategy()
    dump(output / "identity.json", {
        "production": j.PRODUCTION_REVISION, "production_manifest": j.digest(manifest),
        "dataset": j.BASE_DATASET_SHA256, "strategy_identity": identity,
        "positive_source": POSITIVE_HASH, "manual_source": MANUAL_HASH,
        "classifier": j.sha256(Path(__file__).with_name("classifier.py")),
        "runner": j.sha256(Path(__file__)), "modes": args.modes,
        "start": j.ORIGIN, "end": FORMATION_END, "capital": "100000",
        "python": sys.version, "packages": {n: importlib.metadata.version(n) for n in
            ("numpy", "pandas", "exchange-calendars", "pydantic", "cryptography")},
        "seconds": args.seconds, "purpose": "formation diagnostic, not strategy performance verdict"})
    print("VERIFYING_INPUTS", flush=True)
    data = j.JanuaryInputs(args.archive, args.sfp)
    classifier = Classifier.load(args.sources)
    cash = {r["session"]: r for r in data.rows("cash.csv.gz")}
    terminal = terminals(j.supplemented_terminals(data.rows("terminal-events.csv.gz")))
    spins = distributions(data.rows("actions.csv.gz"))
    account = j.EconomicPath(100000)
    scenarios = {}
    for mode in args.modes:
        scenarios[mode] = dict(
            state=j.SessionState.fresh(starting_cash=100000, controller=j.Controller(config),
                                       strategy_identity=identity),
            meta={}, sectors={}, total=0, changes=0,
            economics={"strategy_nav": "100000", "last_session": None,
                       "pending_allocation": None, "held_allocation": None})
    factors = {}
    print("INPUTS_VERIFIED", round(time.monotonic() - started, 2), flush=True)
    traces = {mode: (output / (mode + "-daily.jsonl")).open("w", encoding="utf-8")
              for mode in args.modes}
    failure = None
    try:
        for day, rows in data.sessions():
            if day > FORMATION_END or time.monotonic() >= deadline:
                break
            spy_days = j.previous_sessions(day, 253)
            gap = Decimal(cash[day]["gap_factor"])
            intraday = Decimal(cash[day]["intraday_factor"])
            prices = dict(bil_open_signal=str(gap), bil_close_signal=str(gap * intraday),
                          bil_close_adjusted=str(gap * intraday), bil_close_unadjusted=str(gap * intraday),
                          bil_previous_close_adjusted="1",
                          bil_previous_session=j.previous_sessions(day, 2)[0])
            for mode, scenario in scenarios.items():
                if time.monotonic() >= deadline:
                    break
                state = scenario["state"]
                corrected = rows if mode == "control" else [classifier.apply(row, mode) for row in rows]
                meta, sectors = dict(scenario["meta"]), dict(scenario["sectors"])
                changes = sum(r["security_type"] != old["security_type"] for r, old in zip(corrected, rows))
                for row in corrected:
                    sid = row["security_id"]
                    meta[sid], sectors[sid] = metadata(row), row["ff12"] or None
                anchors = {r["security_id"]: j.FeedAnchor(r["security_id"], r["ticker"],
                           meta[r["security_id"]].issuer_key()[0], factors.get(r["security_id"], 1.0))
                           for r in corrected if r["security_id"] not in state.feed["series"]}
                published = j.PublishedSession(
                    session=day, data_version=1, bars=[vendor(r) for r in corrected],
                    meta=meta, sectors=sectors,
                    spy_closeadj=[float(data.benchmark[d]) for d in spy_days],
                    spy_sessions=spy_days, spy_expected_sessions=spy_days, feed_anchors=anchors,
                    terminal_events=terminal.get(day, ()), spinoff_distributions=spins.get(day, ()))
                candidate = j.advance_session(state, published, controller_config=config, strategy_identity=identity)
                economics = account.advance(previous=scenario["economics"], state=candidate, strategy_prices=prices)
                scenario.update(state=candidate, economics=economics, meta=meta, sectors=sectors,
                                total=scenario["total"] + 1, changes=scenario["changes"] + changes)
                record = dict(date=day, nav=economics["strategy_nav"],
                              core_nav=economics["parent_core_close_equity"],
                              changed_classifications=changes, decision=candidate.last_decision,
                              held_count=len(candidate.wealth_core["episodes"]))
                if day >= "2006-07-05":
                    record.update(holdings=candidate.wealth_core["episodes"], pending=candidate.pending,
                                  ledger=candidate.ledger, economics=economics)
                traces[mode].write(json.dumps(record, allow_nan=False) + "\n")
                traces[mode].flush()
            for row in rows:
                sid = row["security_id"]
                factors[sid] = factors.get(sid, 1.0) * number(row["split_ratio"])
            if scenarios[args.modes[0]]["total"] % 20 == 0 or day >= "2006-07-05":
                print(day, {m: s["economics"]["strategy_nav"] for m, s in scenarios.items()},
                      "elapsed", round(time.monotonic() - started, 2), flush=True)
    except Exception as exc:
        failure = dict(session=day, mode=mode, error=repr(exc), traceback=traceback.format_exc())
    finally:
        for stream in traces.values():
            stream.close()
    result = dict(status="REFUSED" if failure else "BOUNDED_DIAGNOSTIC",
                  elapsed_seconds=round(time.monotonic() - started, 2), failure=failure, scenarios={})
    for mode, scenario in scenarios.items():
        state = scenario["state"]
        snapshot = dict(last_session=state.last_processed_session, total_sessions=scenario["total"],
                        nav=scenario["economics"]["strategy_nav"],
                        changed_observations=scenario["changes"],
                        core_nav=scenario["economics"].get("parent_core_close_equity"),
                        holdings=state.wealth_core["episodes"], pending=state.pending,
                        ledger=state.ledger, economics=scenario["economics"])
        dump(output / (mode + "-final.json"), snapshot)
        result["scenarios"][mode] = {k: snapshot[k] for k in
                                    ("last_session", "total_sessions", "nav", "core_nav", "changed_observations")}
    dump(output / "result.json", result)
    print(json.dumps(result), flush=True)
    return 2 if failure else 0


if __name__ == "__main__":
    raise SystemExit(main())
