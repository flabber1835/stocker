#!/usr/bin/env python3
"""Independent session-by-session Median-5 equivalence on the immutable PIT tape.

Research dependencies live in an isolated pinned checkout supplied by the
caller. This harness never imports research into production modules.
"""
from __future__ import annotations

import argparse
import ast
import csv
from dataclasses import replace
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import types
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
HARNESS_SHA = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

from tools.median5_reference import verify as verify_dependencies

import numpy as np
import pandas as pd

from sentinel.controller.machine import Controller
from sentinel.controller.median5 import load
from sentinel.core.decision import runtime_strategy_identity
from sentinel.core.kernel import advance_session
from sentinel.core.session import FeedAnchor, PublishedSession, SessionState
from stock_strategy_shared.wealth_core.feed import SecurityMeta, VendorBar
from stock_strategy_shared.wealth_core import adapter

AST_SHA = "11c94a61c145261daac81047cf7b7bb1ea0c97b369476458d83fc29fbc10de95"
DATA_SHA = "5bdc6b39e4a8ec4d3e4cebba6091b18a8b4032b41509581366bb60c0d0600993"
ABS_TOL = 0.0001
RATIO_ABS_TOL = 1e-12
REL_TOL = 1e-12
FRACTIONAL_SHARE_ULPS = 4


def prepare_output(output):
    if output.exists() and any(output.iterdir()):
        raise ValueError("equivalence output must be empty; preserve each run separately")
    output.mkdir(parents=True, exist_ok=True)


def normalized_sha(source):
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "OUT" for t in node.targets):
            node.value = ast.Constant("<OUTPUT_PATH>")
    return hashlib.sha256(ast.dump(tree, include_attributes=False).encode()).hexdigest()


def opening_estimate(state, bars, ledger, prior):
    """Audit-only research valuation of the actual pre-fill production book."""
    current = {bar.security_id: bar.raw_open for bar in bars}
    value = float(state.cash) + ledger.receivable_total()
    carried = []
    def positive(price):
        return price is not None and math.isfinite(price) and price > 0
    for slot in sorted(state.episodes):
        episode = state.episodes[slot]
        sid = episode.security_id
        price = current.get(sid)
        if not positive(price):
            history = prior.feed.get("series", {}).get(sid, {}).get("raw_closes", ())
            price = next((p for p in reversed(history) if positive(p)), prior.last_known.get(sid))
            if not positive(price):
                raise ValueError("opening audit lacks current and prior raw price: " + sid)
            carried.append(sid)
        value += float(episode.current_shares) * float(price)
    return value, tuple(sorted(set(carried)))


def advance_with_open_audit(prior, published, *, controller_config, strategy_identity):
    """Observe the existing opening boundary without changing its return value."""
    observations = []
    original = adapter._resolved_open_equity
    def observe_open(state, bars, ledger):
        resolved = original(state, bars, ledger)
        observations.append(opening_estimate(state, bars, ledger, prior))
        return resolved
    with patch.object(adapter, "_resolved_open_equity", observe_open):
        after = advance_session(prior, published, controller_config=controller_config,
                                strategy_identity=strategy_identity)
    if len(observations) != 1:
        raise AssertionError("opening audit must observe exactly one canonical boundary")
    return after, observations[0]


def inputs(dataset, classifier, end):
    """Input-only adapter; shares no research features, filters, or decisions."""
    levels, _ = dataset.benchmark()
    terminals = dataset.terminal_terms()
    dates = list(dataset.sessions)
    date_index = {s: i for i, s in enumerate(dates)}
    for year in range(2006, int(end[:4])+1):
        frame = dataset.observations(year)
        frame = frame[frame.session <= end]
        for session, group in frame.groupby("session", sort=True):
            bars, meta, anchors = [], {}, {}
            for row in group.itertuples(index=False):
                sid = str(row.security_id)
                factual = dataset.metadata_for(sid, session)
                kind = factual["security_type"] if factual is not None else "unknown"
                if kind == "unknown":
                    try:
                        kind = classifier.classify(sid, session)
                    except RuntimeError as exc:
                        # The frozen factual ledger covers decision-relevant
                        # unknowns. Every other raw unknown remains ineligible;
                        # the independent reference still refuses if one later
                        # reaches its candidate population without authority.
                        if not str(exc).startswith(("unknown canonical candidate absent from estimate ledger:",
                                                    "estimate requested outside admitted interval:",
                                                    "factual correction requested outside admitted interval:",
                                                    "reviewed classification requested outside admitted interval:",
                                                    "unsupported historical extrapolation:")):
                            raise
                        kind = "unknown"
                first = dataset._timeline_rows[sid][0]
                meta[sid] = SecurityMeta(
                    sid, str(first["ticker"]),
                    category="Common Stock" if kind == "common" else None,
                    permaticker=sid, first_session=str(first["listing_first_session"]),
                    exchange_authoritative=False)
                volume = None if pd.isna(row.raw_compatible_volume) else float(row.raw_compatible_volume)
                bars.append(VendorBar(
                    str(session), sid, str(row.ticker), float(row.raw_close),
                    float(row.raw_open), volume, float(row.split_ratio),
                    float(row.dividend_per_share),
                    str(row.tradeable) in {"1", "1.0", "True", "true"},
                    signal_close=float(row.signal_close)))
                anchors[sid] = FeedAnchor(sid, str(row.ticker), f"SID:{sid}",
                    float(row.signal_close)/float(row.raw_close)/float(row.split_ratio))
            index = date_index[session]
            spy_dates = dates[max(0, index-40):index+1]
            terms = tuple(replace(t, delivered_issuer_id=(
                f"SID:{t.delivered_security_id}" if t.delivered_security_id else None))
                for t in terminals.get(session, ()))
            yield PublishedSession(str(session), 1, bars, meta, {},
                [levels[s] for s in spy_dates], spy_dates, spy_dates, terms, anchors)


class Comparison:
    def __init__(self, dataset, classifier, end, output, restart_every, *,
                 controller_factory=load, starting_cash=100_000_000., v5=False):
        self.inputs = iter(inputs(dataset, classifier, end))
        self.controller = controller_factory()
        self.v5 = v5
        self.identity = runtime_strategy_identity(self.controller)
        self.state = SessionState.fresh(starting_cash=starting_cash,
            controller=Controller(self.controller), strategy_identity=self.identity)
        self.cash_factors = dataset.cash_factors()
        self.output, self.restart_every = output, restart_every
        self.count = self.measured = self.restarts = 0
        self.rows = []
        self.previous_equity = None
        self.allocation = self.pending = 1.
        self.nav = 1.
        self.maximum_error = 0.
        self.maximum_ratio_error = 0.
        self.fractional_share_roundoffs = 0
        self.estimated_open_sessions = []
        self.estimated_open_transitions = []

    def shares(self, name, actual, expected):
        actual, expected = float(actual), float(expected)
        if actual == expected:
            return
        # Entry orders and integer quantities are discrete and exact. Canonical
        # decimal serialization and the research binary split product may
        # differ by a few machine representable steps for fractional holdings.
        if (math.isfinite(actual) and math.isfinite(expected)
                and not actual.is_integer() and not expected.is_integer()
                and abs(actual-expected) <= FRACTIONAL_SHARE_ULPS * max(math.ulp(actual), math.ulp(expected))):
            self.fractional_share_roundoffs += 1
            return
        self.equal(name, actual, expected)

    def equal(self, name, actual, expected, *, numeric=False):
        monetary = name in {"cash", "receivables", "shadow_nav", "open_equity"}
        tolerance = ABS_TOL if monetary else RATIO_ABS_TOL
        if numeric and actual is not None and expected is not None:
            error = abs(float(actual)-float(expected))
            self.maximum_error = max(self.maximum_error, error)
            if not monetary:
                self.maximum_ratio_error = max(self.maximum_ratio_error, error)
            good = math.isclose(actual, expected, abs_tol=tolerance, rel_tol=REL_TOL)
        else:
            good = actual == expected
        if not good:
            failure = {"status": "FAIL", "session": self.session, "field": name,
                       "production": actual, "research": expected,
                       "sessions_compared": self.count,
                       "abs_tolerance": tolerance, "relative_tolerance": REL_TOL}
            failure["diagnostics"] = getattr(self, "diagnostics", {})
            (self.output/"first-divergence.json").write_text(json.dumps(failure, indent=2, default=str))
            raise AssertionError(json.dumps(failure, default=str))

    def observe(self, research):
        published = next(self.inputs)
        self.session = published.session
        self.equal("session", self.session, research["ds"])
        before = self.state
        self.state, (opened, carried) = advance_with_open_audit(
            before, published, controller_config=self.controller, strategy_identity=self.identity)
        after = self.state
        if self.restart_every and self.count % self.restart_every == 0:
            restored = SessionState.from_dict(json.loads(json.dumps(before.to_dict(), allow_nan=False)))
            replayed = advance_session(restored, published, controller_config=self.controller,
                                      strategy_identity=self.identity)
            self.equal("restart", replayed.state_hash, after.state_hash)
            self.restarts += 1
        wealth, ref = after.wealth_core, research["book"]
        sid = research["sid"]
        self.diagnostics = {
            "session_index": research["gday"],
            "production_slots": wealth["slots"],
            "reference_slots": [vars(s) for s in ref.slots],
            "production_blocked": after.last_evidence["wealth_core"]["blocked"],
            "reference_unresolved": bool(research["unresolved"]),
            "reference_terminal_pending": {str(sid[k]): v for k, v in ref.terminal_pending.items()},
            "production_terminal_pending": wealth["terminal_pending_sessions"],
            "reference_missing_held_prices": [str(sid[s.tid]) for s in ref.slots
                if s.held() and not np.isfinite(research["clraw"][s.tid])],
            "reference_holding_features": research["held"],
            "opening_audit_equity": opened,
            "opening_audit_carried_security_ids": carried,
        }
        ref_order = [str(sid[int(t)]) for t in research["durable"]]
        self.equal("durable_order", wealth["median5"]["rank_history"][-1], ref_order)
        self.equal("eligible_population", after.last_evidence["median5_eligible_population"], len(research["et"]))
        self.equal("cash", wealth["cash"], ref.cash, numeric=True)
        self.equal("receivables", sum(r["amount"] for r in after.ledger["receivables"]),
                   sum(r[1] for r in ref.receivables), numeric=True)
        actual_held = {int(k): (v["security_id"], float(v["current_shares"])) for k, v in wealth["episodes"].items()}
        expected_held = {i: (str(sid[s.tid]), s.qty) for i, s in enumerate(ref.slots) if s.held()}
        self.equal("held_slots_and_securities", {k: v[0] for k, v in actual_held.items()},
                   {k: v[0] for k, v in expected_held.items()})
        for slot, (_sid, quantity) in actual_held.items():
            self.shares(f"slot_{slot}_quantity", quantity, expected_held[slot][1])
        expected_pending = []
        for i, slot in enumerate(ref.slots):
            if slot.held() and slot.pending_sell:
                expected_pending.append((i, str(sid[slot.tid]), "CLOSE_POSITION", slot.qty))
            if slot.reserved():
                expected_pending.append((i, str(sid[slot.pending_tid]), "OPEN_SLOT_POSITION", slot.pending_shares))
        actual_pending = [(p["slot_id"], p["security_id"], p["operation"], p["shares"]) for p in after.pending]
        actual_pending, expected_pending = sorted(actual_pending), sorted(expected_pending)
        self.equal("pending_order_identities", [p[:3] for p in actual_pending], [p[:3] for p in expected_pending])
        for actual, expected in zip(actual_pending, expected_pending):
            if actual[2] == "OPEN_SLOT_POSITION":
                self.equal(f"slot_{actual[0]}_entry_quantity", actual[3], expected[3])
                if self.v5:
                    pending = next(p for p in after.pending if p["slot_id"] == actual[0])
                    self.equal(f"slot_{actual[0]}_intended_dollars", pending["intended_dollars"],
                               ref.slots[actual[0]].pending_intended_capital, numeric=True)
            else:
                self.shares(f"slot_{actual[0]}_exit_quantity", actual[3], expected[3])
        for slot, (_, _) in actual_held.items():
            ep, expected = wealth["episodes"][str(slot)], ref.slots[slot]
            self.equal(f"slot_{slot}_age", ep["market_sessions_held"], research["gday"]-expected.entry_day)
            self.equal(f"slot_{slot}_peak", ep["episode_peak_split_adjusted_close"], expected.peak, numeric=True)
            self.equal(f"slot_{slot}_review", ep["review_completed"], expected.reviewed)
            self.equal(f"slot_{slot}_entry", ep["entry_split_adjusted_price"], expected.entry_sig, numeric=True)
        evidence = after.last_evidence
        for field, expected in (("damaged_breadth", research["dam_b"]), ("green_breadth", research["green_b"]),
                                ("shadow_nav", research["eq"])):
            self.equal(field, evidence["observation"][field], expected, numeric=True)
        for field in ("recent_r20", "recent_r40"):
            self.equal(field, evidence["recent_leadership"][field], research[field], numeric=True)
        self.equal("native_allocation", after.last_decision["native_target_core_exposure"], research["native_target"])
        self.equal("final_allocation", after.last_decision["target_core_exposure"], research["a_d"])
        self.equal("recovery_reason", after.last_decision["ldrc"]["reason"], research["a_reason"])
        nav = float(evidence["observation"]["shadow_nav"])
        resolved_open = evidence["wealth_core"]["resolved_open_equity"]
        self.equal("open_equity", opened, research["open_eq"], numeric=True)
        self.equal("unresolved_open_securities", list(carried),
                   evidence["wealth_core"]["open_unresolved_security_ids"])
        if carried:
            self.equal("strict_open_remains_unresolved", resolved_open, None)
            self.estimated_open_sessions.append({"session": self.session, "security_ids": list(carried)})
        else:
            self.equal("open_equity", opened, resolved_open, numeric=True)
        if self.session >= "2006-07-31":
            if self.previous_equity is not None:
                gap, intraday = self.cash_factors[self.session]
                old, new = self.allocation, self.pending
                if abs(old-new) < 1e-15:
                    factor = old*nav/self.previous_equity + (1-old)*gap*intraday
                else:
                    if carried:
                        self.estimated_open_transitions.append({"session": self.session,
                            "security_ids": list(carried), "old_allocation": old, "new_allocation": new})
                    factor = (1+old*(opened/self.previous_equity-1)+(1-old)*(gap-1))
                    factor *= 1-0.001*abs(new-old)
                    factor *= 1+new*(nav/opened-1)+(1-new)*(intraday-1)
                self.nav *= factor
            self.allocation = self.pending
            self.equal("effective_allocation", self.allocation, research["eff"]["A"])
            self.equal("scalar_nav", self.nav, research["navs"]["A"], numeric=True)
            self.previous_equity = nav
            self.measured += 1
        self.pending = after.last_decision["target_core_exposure"]
        self.count += 1
        self.rows.append({"session": self.session, "wealth_core_equity": nav,
                          "opening_audit_equity": opened,
                          "opening_audit_carried_security_ids": json.dumps(list(carried)),
                          "native_target": after.last_decision["native_target_core_exposure"],
                          "final_target": self.pending, "allocation": self.allocation, "nav": self.nav})
        if self.count % (10 if self.count <= 150 else 50) == 0:
            print(f"EQUIVALENCE sessions={self.count} through={self.session} restarts={self.restarts}", flush=True)


def main(*, profile="median5"):
    if profile not in ("median5", "v5"):
        raise ValueError("unsupported equivalence profile")
    v5 = profile == "v5"
    reference_ast = ("a65fe9f187e4a2bd5864e095e3a338b38175db97100715f5fcca27856e2450a3"
                     if v5 else AST_SHA)
    parser = argparse.ArgumentParser()
    parser.add_argument("--research-root", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--through", default="2026-07-31")
    parser.add_argument("--restart-every", type=int, default=251)
    parser.add_argument("--verified-cache", type=Path)
    args = parser.parse_args()
    root, dataset_path, output = args.research_root.resolve(), args.dataset.resolve(), args.output.resolve()
    prepare_output(output)
    dependency_sha = verify_dependencies(root)
    sys.path.append(str(root))
    from backtester.canonical_pit_dataset import CanonicalPITDataset
    from backtester import champion_final_security_truth as classifier
    from backtester.research_champion_best_effort_classification import DEFAULT_LEDGER
    cache_path = args.verified_cache.resolve() if args.verified_cache else None
    from backtester import canonical_pit_dataset as data_module
    validator_sha = hashlib.sha256(Path(data_module.__file__).read_bytes()).hexdigest()
    if cache_path is not None and cache_path.exists() and args.through != "2026-07-31":
        cached = json.loads(cache_path.read_text())
        assert cached["validator_sha256"] == validator_sha
        assert cached["root"] == str(dataset_path)
        assert cached["manifest_sha256"] == hashlib.sha256((dataset_path/"manifest.json").read_bytes()).hexdigest()
        for name, member in cached["attributes"]["manifest"]["members"].items():
            with (dataset_path/name).open("rb") as stream:
                assert hashlib.file_digest(stream, "sha256").hexdigest() == member["sha256"], name
        dataset = CanonicalPITDataset.__new__(CanonicalPITDataset)
        dataset.__dict__.update(cached["attributes"])
        dataset.root = dataset_path
        dataset.manifest_path = dataset_path/"manifest.json"
        dataset.sessions = tuple(dataset.sessions)
        print("Reused complete validation after rehashing every immutable input member", flush=True)
    else:
        print("Validating all canonical PIT members and row contracts", flush=True)
        dataset = CanonicalPITDataset(dataset_path)
        if cache_path is not None:
            cache_path.write_text(json.dumps({"validator_sha256": validator_sha,
                "root": str(dataset_path),
                "manifest_sha256": hashlib.sha256((dataset_path/"manifest.json").read_bytes()).hexdigest(),
                "attributes": dataset.__dict__}, default=str))
        print("Complete immutable input validation passed", flush=True)
    assert dataset.dataset_hash == DATA_SHA
    os.environ["CANONICAL_PIT_DATASET"] = str(dataset_path)
    os.environ["BEST_EFFORT_SECURITY_TYPES"] = str(DEFAULT_LEDGER)
    os.environ["BEST_EFFORT_CLASSIFICATION_SCENARIO"] = "reviewed_18"
    os.environ["RESEARCH_REPLAY_MODE"] = "fullpit"
    engine = output/"research"
    engine.mkdir(exist_ok=True)
    source = (REPO/f"tests/{profile}/frozen_reference.txt").read_text()
    assert normalized_sha(source) == reference_ast
    if v5:
        from stock_strategy_shared.wealth_core.v5 import REFERENCE_SOURCE_SHA256
        assert hashlib.sha256(source.encode()).hexdigest() == REFERENCE_SOURCE_SHA256
    # A sole observation after the completed transition. Removing it must
    # restore the exact normalized research AST; no economic statement moves.
    anchor = "            pending_native=native_target; pend['control']=a_d; pend['A']=a_d; pend['B']=b_d"
    injected = anchor + "\n            _capture(locals())"
    assert source.count(anchor) == 1
    instrumented = source.replace(anchor, injected)
    assert normalized_sha(instrumented.replace(injected, anchor)) == reference_ast
    tree = ast.parse(instrumented)
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "OUT" for t in node.targets):
            node.value = ast.Call(ast.Name("Path", ast.Load()), [ast.Constant(str(engine))], [])
    ast.fix_missing_locations(tree)
    module = types.ModuleType("frozen_median5_equivalence_reference")
    sys.modules[module.__name__] = module
    from sentinel.controller.ex3_v6 import load as v5_load
    comparison = Comparison(dataset, classifier.SecurityTypeEstimate(DEFAULT_LEDGER, "reviewed_18"), args.through, output, args.restart_every,
        controller_factory=v5_load if v5 else load, starting_cash=100_000. if v5 else 100_000_000., v5=v5)
    previous_cwd = Path.cwd()
    try:
        os.chdir(root)
        exec(compile(tree, str(REPO/f"tests/{profile}/frozen_reference.txt"), "exec"), module.__dict__)
        def capture(research):
            try:
                comparison.observe(research)
            except Exception as exc:
                failure = output/"first-divergence.json"
                if not failure.exists():
                    failure.write_text(json.dumps({"status": "FAIL",
                        "session": getattr(comparison, "session", research.get("ds")),
                        "sessions_compared": comparison.count,
                        "exception": type(exc).__name__, "message": str(exc),
                        "diagnostics": getattr(comparison, "diagnostics", {})}, indent=2, default=str)+"\n")
                print(failure.read_text(), flush=True)
                raise
        module._capture = capture
        module.CanonicalPITDataset = lambda *a, **kw: dataset
        module.END = pd.Timestamp(args.through)
        module.run()
    finally:
        os.chdir(previous_cwd)
    complete = args.through == "2026-07-31" and comparison.measured == 5032
    research_summary = json.loads((engine/"summary.json").read_text())
    if args.through == "2026-07-31":
        comparison.equal("complete_session_count", comparison.count, 5176)
        comparison.equal("complete_measured_count", comparison.measured, 5032)
        expected_metrics = ({"cagr": .21557225805610547,
                                "max_drawdown": -.2737554573856501,
                                "sharpe": 1.1210581190467033,
                                "ending_multiple": 49.61927543842201} if v5 else {"cagr": .19701208470494502,
                                "max_drawdown": -.26388132212279014,
                                "sharpe": 1.0471046041739411,
                                "ending_multiple": 36.47562758311568})
        for field, expected in expected_metrics.items():
            comparison.equal("certified_reference_"+field,
                             research_summary["metrics"]["A"][field], expected, numeric=True)
        comparison.equal("certified_reference_buys", research_summary["buys"], 416 if v5 else 426)
        comparison.equal("certified_reference_sells", research_summary["sells"], 350 if v5 else 363)
        comparison.equal("certified_reference_transitions", research_summary["transition_counts"]["A"], 28 if v5 else 25)
        comparison.equal("certified_reference_zero_allocation_sessions",
                         sum(row["allocation"] == 0 for row in comparison.rows
                             if row["session"] >= "2006-07-31"), 634 if v5 else 459)
        if v5:
            for name, expected in {
                "transactions.csv": "0e4828229c323ab029a5dfe49f258a3e2e379aee6b5e18169e72f9edc88652da",
                "close-decisions.csv": "d1f557bd139e3445538e3f94bce90fe296eba19450d939c4160fe0880e067724",
            }.items():
                comparison.equal("reference_"+name, hashlib.sha256((engine/name).read_bytes()).hexdigest(), expected)
        comparison.equal("production_identity_unchanged", runtime_strategy_identity(comparison.controller), comparison.identity)
    result = {"status": "PASS_FULL_PIT_EQUIVALENCE" if complete else "PASS_PARTIAL_EQUIVALENCE",
              "profile": profile,
              "strategy_identity": comparison.identity,
              "dataset_sha256": DATA_SHA, "reference_normalized_ast_sha256": reference_ast,
              "reference_dependency_sha256": dependency_sha,
              "harness_source_sha256": HARNESS_SHA,
              "runtime": {"python": sys.version, "numpy": np.__version__, "pandas": pd.__version__},
              "dependency_locks": {name: hashlib.sha256((REPO/name).read_bytes()).hexdigest()
                                   for name in ("sentinel/requirements.lock", "tests/requirements.lock")},
              "research_metrics": research_summary["metrics"]["A"],
              "sessions": comparison.count, "measured_sessions": comparison.measured,
              "restart_comparisons": comparison.restarts,
              "numeric_absolute_tolerance": ABS_TOL, "numeric_relative_tolerance": REL_TOL,
              "nonmonetary_absolute_tolerance": RATIO_ABS_TOL,
              "maximum_absolute_numeric_difference": comparison.maximum_error,
              "maximum_absolute_nonmonetary_difference": comparison.maximum_ratio_error,
              "fractional_share_tolerance_ulps": FRACTIONAL_SHARE_ULPS,
              "fractional_share_roundoff_comparisons": comparison.fractional_share_roundoffs,
              "opening_valuation_convention": "current raw open, else prior raw observation; audit only",
              "estimated_open_sessions": comparison.estimated_open_sessions,
              "estimated_open_allocation_transitions": comparison.estimated_open_transitions,
              "production_identity": comparison.identity}
    (output/"RESULT.json").write_text(json.dumps(result, indent=2)+"\n")
    with (output/"production-daily.csv").open("w") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(comparison.rows[0]))
        writer.writeheader(); writer.writerows(comparison.rows)
    print(json.dumps(result, indent=2), flush=True)


if __name__ == "__main__":
    main()
