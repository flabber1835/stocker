"""Provisional offline economic replay; never grants publication/broker authority."""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import date
from decimal import Decimal
import gzip
import hashlib
import json
import math
from pathlib import Path
import time
import traceback
from types import SimpleNamespace

from stock_strategy_shared.wealth_core.feed import (
    DecisionMetadataTimelineBuilder, SecurityMeta, VendorBar)
from stock_strategy_shared.wealth_core.terminal import TerminalKind, TerminalTerms
from sentinel.controller.machine import Controller
from sentinel.core.kernel import advance_session
from sentinel.core.production import warm_session_state
from sentinel.core.session import FeedAnchor, PublishedSession, SessionState
from sentinel.core.spinoffs import SpinoffDistribution
from sentinel.feed.calendar import previous_sessions
from sentinel.shadow_observation import ShadowObserver
from sentinel.strategy import production_strategy

from .inputs import Inputs
from .supplement import RSAS, supplemented_terminals

START = "2006-07-31"
END = "2026-07-31"
PRODUCTION_REVISION = "ee23c894c97a2c4023654ce3a56a62728f5b061e"


def budget_decision(*, elapsed, measured_seconds, completed, total,
                    pilot_seconds, max_seconds):
    """Project sequential continuation, never extrapolate investment returns."""
    if elapsed >= max_seconds:
        return "BUDGET_STOP", None
    if elapsed < pilot_seconds:
        return "PILOT", None
    if completed <= 0:
        return "PILOT_TOO_SLOW", None
    projected = elapsed + measured_seconds / completed * (total - completed) * 1.2
    return ("CONTINUE" if projected <= max_seconds else "PILOT_TOO_SLOW"), projected


def verify_production(root, manifest):
    if manifest["revision"] != PRODUCTION_REVISION:
        raise ValueError("experiment production revision differs")
    for name, expected in manifest["files"].items():
        observed = hashlib.sha256((root / name).read_bytes()).hexdigest()
        if observed != expected:
            raise ValueError("experiment production source differs: " + name)


class EconomicPath:
    """Call the production scalar accountant without constructing service authority."""
    _allocation = staticmethod(ShadowObserver._allocation)
    _parent_economics = ShadowObserver._parent_economics
    advance = ShadowObserver._advance_strategy_economics

    def __init__(self, capital):
        self.starting_cash = str(capital)


def number(value):
    if value == "":
        return None
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("nonfinite source numeric value")
    return result


def metadata(row):
    eligible = row["security_type_eligible"] == "1"
    if eligible != (row["security_type"] == "common"):
        raise ValueError("source classification and eligibility disagree")
    return SecurityMeta(
        row["security_id"], row["ticker"],
        category="Domestic Common Stock" if eligible else None,
        permaticker=row["issuer_id"],
        first_session=row["listing_first_session"] or row["session"],
        exchange=None, exchange_authoritative=False)


def vendor(row):
    return VendorBar(
        row["session"], row["security_id"], row["ticker"],
        number(row["raw_close"]), number(row["raw_open"]),
        number(row["raw_compatible_volume"]),
        split_ratio=number(row["split_ratio"]),
        dividend_per_share=number(row["dividend_per_share"]),
        tradeable=row["tradeable"] == "1", signal_close=number(row["signal_close"]))


def terminals(rows):
    result = defaultdict(list)
    for row in rows:
        term = TerminalTerms(
            session=row["effective_session"], security_id=row["security_id"],
            kind=TerminalKind(row["kind"]), reference=row["reference"],
            cash_per_share=number(row["cash_per_share"]),
            delivered_security_id=row["delivered_security_id"] or None,
            delivered_ticker=row["delivered_ticker"] or None,
            delivered_issuer_id=row["delivered_issuer_id"] or None,
            exchange_ratio=number(row["exchange_ratio"]),
            cash_in_lieu_price_per_delivered_share=number(row["cash_in_lieu_price_per_delivered_share"]))
        result[term.session].append(term)
    return result


def distributions(rows):
    result = defaultdict(list)
    for row in rows:
        if row["action"].lower() not in {"spinoff", "spinoffdividend"}:
            continue
        digest = hashlib.sha256(json.dumps(row, sort_keys=True).encode()).hexdigest()
        result[row["effective_session"]].append(SpinoffDistribution(
            session=row["effective_session"], parent_ticker=row["ticker"],
            parent_security_id=row["security_id"] or None,
            child_ticker=None, child_security_id=None, source_row_id=digest,
            value_evidence=row["vendor_value"]))
    return result


def performance(rows):
    if not rows or rows[0]["session"] != START or rows[-1]["session"] != END:
        raise ValueError("a prefix cannot supply the requested twenty-year result")
    expected = previous_sessions(END, len(rows))
    if [r["session"] for r in rows] != expected:
        raise ValueError("measured session schedule has gaps or duplicates")
    years = Decimal((date.fromisoformat(END) - date.fromisoformat(START)).days) / Decimal("365.25")
    result = {}
    for label, key in (("combined", "strategy_nav"), ("wealth_core", "core_nav"), ("spy", "spy")):
        values = [Decimal(r[key]) for r in rows]
        if any(not v.is_finite() or v <= 0 for v in values):
            raise ValueError("invalid performance NAV")
        multiple = values[-1] / values[0]
        peak, dd = values[0], Decimal(0)
        for value in values:
            peak = max(peak, value)
            dd = min(dd, value / peak - 1)
        result[label] = {"multiple": str(multiple),
                         "cagr": math.expm1(math.log(float(multiple)) / float(years)),
                         "maximum_drawdown": str(dd)}
    return {"years": str(years), "measured_sessions": len(rows), **result}


def dump(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def run(args):
    if not args.capital.is_finite() or args.capital <= 0:
        raise ValueError("starting capital must be positive and finite")
    if not 0 < args.pilot_seconds < args.max_seconds <= 7200:
        raise ValueError("execution budget must satisfy 0 < pilot < maximum <= 7200")
    args.output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    root = Path(__file__).resolve().parents[2]
    source_manifest = json.loads(Path(__file__).with_name("production-source.json").read_text(encoding="utf-8"))
    verify_production(root, source_manifest)
    data = Inputs(args.archive, args.prefix, args.sfp)
    config, identity = production_strategy()
    dump(args.output / "identity.json", {
        "production_revision": PRODUCTION_REVISION, "strategy_identity": identity,
        "production_files": source_manifest["files"],
        "benchmark_bridge": data.benchmark_bridge,
        "harness_files": {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                          for name in ("run.py", "inputs.py", "supplement.py")},
        "terminal_supplement": RSAS,
        "pilot_seconds": args.pilot_seconds, "maximum_seconds": args.max_seconds,
        "base_manifest": data.base, "prefix_manifest": data.prefix,
        "starting_cash": str(args.capital), "measurement_start": START,
        "measurement_end": END, "status": "PROVISIONAL_ENGINE_ONLY",
        "source_scenario": "retained-schema-2-base-plus-RSAS-supplement-and-causal-2005-prefix",
        "scope": "canonical kernel and scalar accounting; no publication, broker or NAS qualification"})
    print("INPUTS_VERIFIED", flush=True)
    required = previous_sessions(START, 253)[:-1]
    benchmark = {r["session"]: r for r in data.benchmark()}
    cash = {r["session"]: r for r in data.small_rows("cash.csv.gz")}
    terminal = terminals(supplemented_terminals(data.small_rows("terminal-events.csv.gz")))
    spinoffs = distributions(data.small_rows("actions.csv.gz"))
    state = SessionState.fresh(starting_cash=float(args.capital),
        controller=Controller(config), strategy_identity=identity)
    timeline = DecisionMetadataTimelineBuilder(required)
    bars_by_day, meta, sectors, factors = {}, {}, {}, {}
    source = iter(data.sessions())
    warm_days = []
    for day, rows in source:
        if day >= START:
            first = (day, rows)
            break
        if day not in required:
            raise ValueError("unexpected warmup session " + day)
        warm_days.append(day)
        for row in rows:
            sid = row["security_id"]
            meta[sid] = metadata(row)
            sectors[sid] = row["ff12"] or None
            factors[sid] = factors.get(sid, 1.0) * number(row["split_ratio"])
        timeline.add_snapshot(day, dict(meta))
        bars_by_day[day] = [vendor(row) for row in rows]
    else:
        raise ValueError("no measured observations")
    if warm_days != required:
        raise ValueError("incomplete exact production warmup")
    window = SimpleNamespace(sessions=warm_days, bars_by_session=bars_by_day,
        meta=meta, metadata_timeline=timeline.finish(),
        median5_spy_closes={d: number(benchmark[d]["level"]) for d in required},
        median5_terminals={d: {t.security_id for t in terminal.get(d, ())} for d in required})
    state = warm_session_state(state, window, publication_version=1)
    del window, bars_by_day, timeline
    print("WARMUP_COMPLETE", len(required), time.monotonic()-started, flush=True)
    measured_started = time.monotonic()
    total_sessions = len([d for d in previous_sessions(END, 6000) if d >= START])
    pilot_accepted = False
    account = EconomicPath(args.capital)
    economics = {"strategy_nav": str(args.capital), "last_session": None,
                 "pending_allocation": None, "held_allocation": None}
    measured = []
    from itertools import chain
    with (args.output / "daily.jsonl").open("w", encoding="utf-8") as trace:
        for day, rows in chain([first], source):
            if day > args.end:
                break
            now = time.monotonic()
            status, projection = budget_decision(
                elapsed=now-started, measured_seconds=now-measured_started,
                completed=len(measured), total=total_sessions,
                pilot_seconds=args.pilot_seconds, max_seconds=args.max_seconds)
            if status in {"BUDGET_STOP", "PILOT_TOO_SLOW"}:
                result = {"status": status, "completed_sessions": len(measured),
                          "last_completed_session": measured[-1]["session"] if measured else None,
                          "elapsed_seconds": now-started, "projected_total_seconds": projection,
                          "twenty_year_cagr": None, "twenty_year_multiple": None}
                dump(args.output / "result.json", result)
                print(json.dumps(result), flush=True)
                return 3
            if status == "CONTINUE" and not pilot_accepted:
                pilot_accepted = True
                print("PILOT_ACCEPTED", projection, flush=True)
            before = state
            try:
                for row in rows:
                    sid = row["security_id"]
                    meta[sid] = metadata(row)
                    sectors[sid] = row["ff12"] or None
                anchors = {r["security_id"]: FeedAnchor(r["security_id"], r["ticker"],
                    meta[r["security_id"]].issuer_key()[0], factors.get(r["security_id"], 1.0))
                    for r in rows if r["security_id"] not in state.feed["series"]}
                spy_days = previous_sessions(day, 253)
                published = PublishedSession(session=day, data_version=1,
                    bars=[vendor(r) for r in rows], meta=meta, sectors=sectors,
                    spy_closeadj=[number(benchmark[d]["level"]) for d in spy_days],
                    spy_sessions=spy_days, spy_expected_sessions=spy_days,
                    feed_anchors=anchors, terminal_events=terminal.get(day, ()),
                    spinoff_distributions=spinoffs.get(day, ()))
                state = advance_session(state, published,
                    controller_config=config, strategy_identity=identity)
                prior_day = previous_sessions(day, 2)[0]
                gap = Decimal(cash[day]["gap_factor"])
                intraday = Decimal(cash[day]["intraday_factor"])
                prices = {"bil_open_signal": str(gap), "bil_close_signal": str(gap*intraday),
                    "bil_close_adjusted": str(gap*intraday), "bil_close_unadjusted": str(gap*intraday),
                    "bil_previous_close_adjusted": "1", "bil_previous_session": prior_day}
                economics = account.advance(previous=economics, state=state, strategy_prices=prices)
                row = {"session": day, "strategy_nav": economics["strategy_nav"],
                    "core_nav": economics["parent_core_close_equity"], "spy": benchmark[day]["level"],
                    "held_count": len(state.wealth_core["episodes"]),
                    "economics": economics, "decision": state.last_decision}
                measured.append(row)
                trace.write(json.dumps(row, sort_keys=True, allow_nan=False) + "\n")
                trace.flush()
                for observation in rows:
                    sid = observation["security_id"]
                    factors[sid] = factors.get(sid, 1.0) * number(observation["split_ratio"])
                if len(measured) % 20 == 0 or len(measured) == 1:
                    print(day, "sessions", len(measured), "nav", row["strategy_nav"],
                          "elapsed", round(time.monotonic()-started, 2), flush=True)
                if len(measured) % 300 == 0:
                    raw = state.to_dict()
                    with gzip.open(args.output / f"checkpoint-{day}.json.gz", "wt", encoding="utf-8") as f:
                        json.dump({"state": raw, "economics": economics, "factors": factors}, f, allow_nan=False)
                    state = SessionState.from_dict(json.loads(json.dumps(raw, allow_nan=False)))
            except Exception as exc:
                failure = {"status": "REFUSED", "session": day, "error_type": type(exc).__name__,
                    "elapsed_seconds": time.monotonic()-started,
                    "error": str(exc), "completed_sessions": len(measured),
                    "last_completed_session": measured[-1]["session"] if measured else None,
                    "twenty_year_cagr": None, "twenty_year_multiple": None,
                    "prior_held": before.wealth_core["episodes"],
                    "valuation_evidence": state.last_evidence,
                    "traceback": traceback.format_exc()}
                dump(args.output / "result.json", failure)
                print(json.dumps({k: v for k, v in failure.items() if k not in
                                 {"prior_held", "valuation_evidence", "traceback"}}), flush=True)
                return 2
    if args.end != END:
        result = {"status": "DIAGNOSTIC_PREFIX_ONLY", "completed_sessions": len(measured),
                  "twenty_year_cagr": None, "twenty_year_multiple": None}
    else:
        result = {"status": "PROVISIONAL_ENGINE_ONLY", **performance(measured)}
        result["starting_capital"] = str(args.capital)
        result["final_capital"] = measured[-1]["strategy_nav"]
        result["historical_reference"] = {
            "multiple": "56.26534933655832", "cagr": 0.22323600023175572,
            "comparison_scope": "different initial book, classification and terminal policy; not parity"}
    result["elapsed_seconds"] = time.monotonic()-started
    dump(args.output / "result.json", result)
    print(json.dumps(result), flush=True)
    return 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--prefix", type=Path, required=True)
    parser.add_argument("--sfp", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--capital", type=Decimal, default=Decimal("100000"))
    parser.add_argument("--end", default=END)
    parser.add_argument("--pilot-seconds", type=float, default=600)
    parser.add_argument("--max-seconds", type=float, default=7200)
    return run(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
