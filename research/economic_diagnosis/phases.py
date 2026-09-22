"""Frozen alternatives across predeclared synthetic book-formation phases."""
from __future__ import annotations

import argparse
import copy
import gzip
import hashlib
import importlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import ModuleType, SimpleNamespace

PARAMETERS = "f2a50c7b6ff4c9686f49b6eb53863e8e2b9959bb"
OWNED = "7250ce3d65cc38a103989d460fe3c557a38343c8"
PHASES = (40, 80, 120, 160)
CUTS = (0, 4, 8, 19, 31, 41, 69, 119)


def load_helpers(directory):
    sources = {}
    commit = subprocess.check_output(["git", "rev-parse", PARAMETERS], text=True).strip()
    for name in ("__init__", "pipeline", "pipeline_diagnostics", "study", "holdings", "parameters", "account"):
        path = f"research/impedance/{name}.py"
        raw = subprocess.check_output(["git", "show", f"{commit}:{path}"])
        (directory / f"{name}.py").write_bytes(raw)
        sources[f"{commit}:{path}"] = hashlib.sha256(raw).hexdigest()
    pkg = ModuleType("research.impedance")
    pkg.__path__ = [str(directory)]
    sys.modules[pkg.__name__] = pkg
    raw = subprocess.check_output(["git", "show", f"{OWNED}:sentinel/controller/owned_impairment.py"])
    sources[f"{OWNED}:sentinel/controller/owned_impairment.py"] = hashlib.sha256(raw).hexdigest()
    path = directory / "owned.py"
    path.write_bytes(raw)
    owned = importlib.import_module("research.impedance.owned")
    return (importlib.import_module("research.impedance.pipeline"),
            importlib.import_module("research.impedance.parameters"),
            importlib.import_module("research.impedance.account"), owned, sources)


def run_case(case, origin, helpers):
    from sentinel.core.kernel import advance_session
    from sentinel.core.session import SessionState
    from research.impedance.pipeline_diagnostics import measure
    pipeline, parameters, accounting, owned, _ = helpers
    config, identity, original_state, original_market, formation = origin
    state = SessionState.from_dict(original_state.to_dict())
    market = copy.deepcopy(original_market)
    probes = {name: parameters.ProbeController(name) for name in parameters.PRESETS}
    owned_state, owned_target = owned.fresh(), 1.
    for row in formation:
        for name, probe in probes.items():
            result = probe.step(row)
            if name == "current":
                parameters.assert_baseline(row, result, probe)
                owned_state, extra = owned.step(observation=SimpleNamespace(**(row["observation"] | {"session": row["session"]})),
                                               base_target=result["target"], state=owned_state)
                owned_target = extra["target"]
    names = list(probes) + ["owned"]
    accounts = {name: accounting.Account() for name in names}
    marks = {s: accounting.dec(p) for s, p in market.prices.items()} | {accounting.BILL: accounting.dec(100)}
    targets = {n: p.target for n, p in probes.items()} | {"owned": owned_target}
    for name, account in accounts.items():
        account.rebalance(state, marks, targets[name])
    initial_targets = dict(targets)
    held = {ep["security_id"] for ep in state.wealth_core["episodes"].values()}
    labels, records = formation[-1]["labels"], []
    for day in range(pipeline.LENGTH):
        published = market.advance(case, day, held)
        previous = state
        state = advance_session(previous, published, controller_config=config, strategy_identity=identity)
        if day in CUTS:
            restored = SessionState.from_dict(json.loads(json.dumps(previous.to_dict())))
            assert advance_session(restored, published, controller_config=config, strategy_identity=identity).state_hash == state.state_hash
        row = measure(state, published, labels)
        labels = row["labels"]
        row.update(day=day, variants={})
        decisions = {}
        for name, probe in probes.items():
            before = probe.snapshot()
            decisions[name] = probe.step(row)
            if name == "current":
                parameters.assert_baseline(row, decisions[name], probe)
            if day in CUTS:
                other = parameters.ProbeController(name)
                other.restore(json.loads(json.dumps(before)))
                assert other.step(row) == decisions[name]
                assert other.snapshot() == probe.snapshot()
        owned_before = owned_state
        observation = SimpleNamespace(**(row["observation"] | {"session": row["session"]}))
        owned_state, decisions["owned"] = owned.step(observation=observation,
            base_target=decisions["current"]["target"], state=owned_before)
        if day in CUTS:
            assert owned.step(observation=observation, base_target=decisions["current"]["target"],
                              state=json.loads(json.dumps(owned_before))) == (owned_state, decisions["owned"])
        opens = {b.security_id: accounting.dec(b.raw_open) for b in published.bars} | {accounting.BILL: accounting.dec(100)}
        closes = {b.security_id: accounting.dec(b.raw_close) for b in published.bars} | {accounting.BILL: accounting.dec(100)}
        for name, account in accounts.items():
            before = account.snapshot()
            before_split_marks = {b.security_id: opens[b.security_id]*accounting.dec(b.split_ratio)
                                  for b in published.bars} | {accounting.BILL: accounting.dec(100)}
            before_split_nav = account.nav(before_split_marks)
            account.split(published.bars)
            assert account.nav(opens) == before_split_nav, "split must preserve value before trades"
            execution = account.rebalance(state, opens, targets[name])
            if day in CUTS:
                other = accounting.Account.restore(json.loads(json.dumps(before)))
                other.split(published.bars)
                assert other.rebalance(state, opens, targets[name]) == execution
                assert other.snapshot() == account.snapshot()
            row["variants"][name] = dict(decision=decisions[name], nav=float(account.nav(closes)),
                                          fees=float(account.fees), turnover=float(account.turnover))
            targets[name] = decisions[name]["target"]
        records.append(row)
    summary = {}
    for name in names:
        peak, dd, prior = 100000., 0., initial_targets[name]
        changes = []
        for row in records:
            variant = row["variants"][name]
            peak = max(peak, variant["nav"])
            dd = min(dd, variant["nav"]/peak-1)
            target = variant["decision"]["target"]
            if target != prior:
                changes.append(dict(day=row["day"], before=prior, after=target))
            prior = target
        summary[name] = dict(ending_nav=records[-1]["variants"][name]["nav"], max_drawdown=dd,
            fees=float(accounts[name].fees), turnover=float(accounts[name].turnover), changes=changes,
            days_below_full=sum(r["variants"][name]["decision"]["target"] < 1 for r in records))
        summary[name]["terminal_difference_dollars"] = summary[name]["ending_nav"]-summary["current"]["ending_nav"]
        summary[name]["drawdown_difference_pp"] = 100*(dd-summary["current"]["max_drawdown"])
    return dict(summary=summary, records=records)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="sentinel-mechanics-") as temporary:
        helpers = load_helpers(Path(temporary))
        pipeline, parameters, _, _, sources = helpers
        original_constants = parameters.production_constants()
        phases = {}
        for length in PHASES:
            pipeline.FORMATION = length
            origin = pipeline.make_origin()
            cases = {}
            for case in pipeline.CASES:
                cases[case] = run_case(case, origin, helpers)
                print(f"formation={length} {case}: complete", flush=True)
            for a, b in zip(cases["healthy"]["records"], cases["healthy_split"]["records"]):
                assert a["observation"] == b["observation"]
                for name in a["variants"]:
                    assert a["variants"][name]["decision"] == b["variants"][name]["decision"]
            phases[str(length)] = dict(origin_hash=origin[2].state_hash, identity=origin[1], cases=cases)
            (args.output/f"phase-{length}.json.gz").write_bytes(gzip.compress(json.dumps(phases[str(length)], allow_nan=False).encode(), mtime=0))
        assert parameters.production_constants() == original_constants
        # Prior 80-session economic results are an external, retained acceptance anchor.
        commit = subprocess.check_output(["git", "rev-parse", PARAMETERS], text=True).strip()
        old = json.loads(subprocess.check_output(["git", "show", f"{commit}:audit/parameter-probes/summary.json"]))
        for case in pipeline.CASES:
            for name in parameters.PRESETS:
                for key in ("ending_nav", "max_drawdown", "fees", "turnover"):
                    assert phases["80"]["cases"][case]["summary"][name][key] == old[case][name][key], (case, name, key)
        summary = {phase: {case: result["summary"] for case, result in data["cases"].items()}
                   for phase, data in phases.items()}
        source_paths = ("sentinel/core/kernel.py", "sentinel/controller/champion_frozen.py",
                        "sentinel/controller/median5_breadth.py", "sentinel/controller/median5.py",
                        "shared/stock_strategy_shared/wealth_core/engine.py",
                        "sentinel/execution/projection.py", "research/economic_diagnosis/phases.py")
        sources.update({path: hashlib.sha256(Path(path).read_text(encoding="utf-8").encode()).hexdigest() for path in source_paths})
        report = dict(schema="sentinel.mechanical-phase-panel/1", sources=sources, formation_lengths=PHASES,
            checks=dict(current_controller_parity_closes=sum(PHASES)+len(PHASES)*7*120,
                        canonical_restart_pairs=len(PHASES)*7*len(CUTS),
                        controller_and_account_restart_pairs_each=len(PHASES)*7*len(CUTS)*6,
                        retained_eighty_session_economics_exact=True, neutral_split_observations_decisions=True,
                        split_pretrade_value_preserved=True,
                        production_constants_unchanged=True), phases=summary)
        report["split_terminal_lot_effect_dollars"] = {phase: {
            name: cases["healthy_split"][name]["ending_nav"]-cases["healthy"][name]["ending_nav"]
            for name in cases["healthy"]} for phase, cases in summary.items()}
        (args.output/"phase-summary.json").write_text(json.dumps(report, indent=2)+"\n", encoding="utf-8")
        print(json.dumps(report["checks"]), flush=True)


if __name__ == "__main__":
    main()
