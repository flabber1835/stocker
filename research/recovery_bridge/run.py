"""Finite coherent synthetic comparison; no historical inputs or broker calls."""
import argparse
import copy
from decimal import Decimal as D
import gzip
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace

from .model import RecoveryBridge
from .scenarios import EXTRA, factors
from .sources import load

PHASES = (40, 120)
CUTS = (0, 7, 8, 19, 31, 45, 69, 119)
NAMES = ("current", "owned55", "bridge")


def projection_view(previous, bars):
    """Only prior published holdings, normalized into today's known share units."""
    book = copy.deepcopy(previous.wealth_core)
    ratios = {bar.security_id: D(str(bar.split_ratio)) for bar in bars}
    for ep in book["episodes"].values():
        ep["current_shares"] = str(D(str(ep["current_shares"])) * ratios[ep["security_id"]])
    return SimpleNamespace(wealth_core=book, ledger=previous.ledger)


def reconcile(before, after, execution, bars):
    """Independent signed-trade cash/share oracle, not projection output math."""
    shares = {s: D(q) for s, q in before["shares"].items()}
    for bar in bars:
        if bar.security_id in shares:
            shares[bar.security_id] *= D(str(bar.split_ratio))
    cash, fees = D(before["cash"]), D(0)
    for sid, quantity, price in execution["trades"]:
        q, p = D(quantity), D(price)
        cash -= q*p + abs(q*p)*D(".001")
        fees += abs(q*p)*D(".001")
        shares[sid] = shares.get(sid, D(0)) + q
    shares = {s: str(q) for s, q in shares.items() if q}
    assert abs(cash-D(after["cash"])) < D("1e-18"), "cash conservation"
    assert {s:D(q) for s,q in shares.items()} == {s:D(q) for s,q in after["shares"].items()}, "share conservation"
    assert abs(D(after["fees"])-D(before["fees"])-fees) < D("1e-18"), "fee conservation"
    assert cash >= 0 and all(D(q) >= 0 for q in shares.values())


def factories(parameters, owned):
    return dict(current=lambda: parameters.ProbeController("current"),
                owned55=lambda: owned.Owned55(parameters.ProbeController("current")),
                bridge=lambda: RecoveryBridge(owned.Owned55(parameters.ProbeController("current"))))


def summarize(records, accounts):
    summary = {}
    for name in NAMES:
        peak, drawdown = 100000., 0.
        for row in records:
            nav = float(row["accounts"][name]["close_nav"])
            peak = max(peak, nav)
            drawdown = min(drawdown, nav/peak-1)
        summary[name] = dict(ending_nav=nav, max_drawdown=drawdown, fees=float(accounts[name].fees),
            turnover=float(accounts[name].turnover),
            zero_closes=sum(row["decisions"][name]["target"] == 0 for row in records),
            partial_closes=sum(row["decisions"][name]["target"] == .55 for row in records))
    b, o = summary["bridge"], summary["owned55"]
    summary["screen"] = dict(terminal_delta=b["ending_nav"]-o["ending_nav"],
        drawdown_delta_pp=100*(b["max_drawdown"]-o["max_drawdown"]), fee_delta=b["fees"]-o["fees"])
    summary["bridge_days"] = [row["day"] for row in records if row["decisions"]["bridge"]["bridge"]]
    summary["target_difference_days"] = [row["day"] for row in records
        if row["decisions"]["bridge"]["target"] != row["decisions"]["owned55"]["target"]]
    summary["mechanics"] = dict(minimum_holdings=min(r["held"] for r in records),
        largest_weight=max(r["largest_stock_weight"] for r in records),
        healthy_owned_weak_leaders=sum(r["observation"]["shadow_r20"] > 0 and r["leadership"]["recent_r20"] <= 0 for r in records),
        recovery_held=sum(r["decisions"]["current"]["reason"] == "FULL_RISK_HELD" for r in records),
        native_zero=sum(r["native_multiplier"] == 0 for r in records),
        damage_full=sum(r["observation"]["damaged_breadth"] == 1 for r in records))
    summary["signal_ranges"] = {key: dict(min=min(r["observation"][key] for r in records),
        max=max(r["observation"][key] for r in records),
        distinct=len({r["observation"][key] for r in records}))
        for key in ("shadow_r20", "damaged_breadth", "green_breadth", "spy_vol_ratio")}
    summary["decision_changes"] = {name: [dict(day=r["day"], target=r["decisions"][name]["target"])
        for i,r in enumerate(records) if i == 0 or r["decisions"][name]["target"] != records[i-1]["decisions"][name]["target"]]
        for name in NAMES}
    return summary


def run_case(case, origin, helpers):
    from sentinel.core.kernel import advance_session
    from sentinel.core.session import SessionState
    from research.impedance.pipeline_diagnostics import measure
    pipeline, parameters, accounting, owned, _ = helpers
    config, identity, source_state, source_market, formation = origin
    state, market = SessionState.from_dict(source_state.to_dict()), copy.deepcopy(source_market)
    makers = factories(parameters, owned)
    controllers = {name: maker() for name, maker in makers.items()}
    for row in formation:
        decisions = {name: controller.step(row) for name, controller in controllers.items()}
        parameters.assert_baseline(row, decisions["current"], controllers["current"])
    targets = {name: decisions[name]["target"] for name in NAMES}
    accounts = {name: accounting.Account() for name in NAMES}
    marks = {s: D(str(p)) for s,p in market.prices.items()} | {accounting.BILL:D(100)}
    for name, account in accounts.items():
        account.rebalance(state, marks, targets[name])
    held = {ep["security_id"] for ep in state.wealth_core["episodes"].values()}
    labels, records = formation[-1]["labels"], []
    for day in range(pipeline.LENGTH):
        published = market.advance(case, day, held)
        previous = state
        opens = {b.security_id:D(str(b.raw_open)) for b in published.bars} | {accounting.BILL:D(100)}
        closes = {b.security_id:D(str(b.raw_close)) for b in published.bars} | {accounting.BILL:D(100)}
        view = projection_view(previous, published.bars)
        account_rows = {}
        # Fill BEFORE advancing the day or observing its closing controller decision.
        for name, account in accounts.items():
            before = account.snapshot()
            pre_split_marks = {b.security_id:opens[b.security_id]*D(str(b.split_ratio)) for b in published.bars} | {accounting.BILL:D(100)}
            old_value = account.nav(pre_split_marks)
            account.split(published.bars)
            assert old_value == account.nav(opens), "neutral split value"
            execution = account.rebalance(view, opens, targets[name])
            after = account.snapshot()
            reconcile(before, after, execution, published.bars)
            if day in CUTS:
                other = accounting.Account.restore(json.loads(json.dumps(before)))
                other.split(published.bars)
                assert other.rebalance(view, opens, targets[name]) == execution
                assert other.snapshot() == after
            account_rows[name] = dict(before=before, after=after, execution=execution,
                source_session=previous.last_processed_session, close_nav=str(account.nav(closes)))
        state = advance_session(previous, published, controller_config=config, strategy_identity=identity)
        if day in CUTS:
            restored = SessionState.from_dict(json.loads(json.dumps(previous.to_dict())))
            assert advance_session(restored, published, controller_config=config, strategy_identity=identity).state_hash == state.state_hash
        row = measure(state, published, labels)
        labels, decisions = row["labels"], {}
        for name, controller in controllers.items():
            before = controller.snapshot()
            decisions[name] = controller.step(row)
            if day in CUTS:
                other = makers[name]()
                other.restore(json.loads(json.dumps(before)))
                assert other.step(row) == decisions[name]
                assert other.snapshot() == controller.snapshot()
        parameters.assert_baseline(row, decisions["current"], controllers["current"])
        assert decisions["bridge"]["owned"] == decisions["owned55"], "same owned parent"
        assert decisions["owned55"]["base"] == decisions["current"], "same current parent"
        assert 0 <= decisions["bridge"]["target"] <= decisions["current"]["native"] <= 1
        row.update(day=day, decisions=decisions, accounts=account_rows, core_state_hash=state.state_hash)
        records.append(row)
        targets = {name: decisions[name]["target"] for name in NAMES}
    return dict(summary=summarize(records, accounts), records=records)


def screen(phases):
    cases = [value for phase in phases.values() for value in phase.values()]
    adverse = [s for s in cases if s["screen"]["terminal_delta"] < -2000
               or s["screen"]["drawdown_delta_pp"] < -2 or s["screen"]["fee_delta"] > 250]
    activity = any(s["target_difference_days"] and s["screen"]["terminal_delta"] > 0 for s in cases)
    healthy = all(phase["healthy"]["screen"]["terminal_delta"] == 0 for phase in phases.values())
    return dict(adverse_cases=len(adverse), coherent_improvement=activity, healthy_unchanged=healthy,
                eligible_for_historical_followup=not adverse and activity and healthy)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    if (args.output/"summary.json").exists():
        raise ValueError("preserve completed experiment; choose a new output directory")
    with tempfile.TemporaryDirectory(prefix="recovery-bridge-") as temp:
        helpers = load(Path(temp))
        pipeline, parameters, _, _, sources = helpers
        constants = parameters.production_constants()
        original = pipeline.factors
        pipeline.factors = lambda case, day, sid, held: factors(original, case, day, sid, held)
        phases = {}
        for phase in PHASES:
            pipeline.FORMATION = phase
            origin = pipeline.make_origin()
            phase_results = {}
            for case in pipeline.CASES + EXTRA:
                result = run_case(case, origin, helpers)
                phase_results[case] = result["summary"]
                raw = json.dumps(result, allow_nan=False, separators=(",", ":")).encode()
                path = args.output/f"phase-{phase}-{case}.json.gz"
                path.write_bytes(gzip.compress(raw, mtime=0))
                print(json.dumps(dict(phase=phase, case=case, bridge_days=len(result["summary"]["bridge_days"]),
                    **result["summary"]["screen"])), flush=True)
            phases[str(phase)] = phase_results
        assert parameters.production_constants() == constants
        for path in ("sentinel/core/kernel.py", "sentinel/core/production.py", "sentinel/controller/champion_frozen.py",
                     "sentinel/controller/median5.py", "sentinel/controller/median5_breadth.py",
                     "sentinel/execution/projection.py", "shared/stock_strategy_shared/wealth_core/engine.py"):
            sources[path] = hashlib.sha256(Path(path).read_bytes()).hexdigest()
        for path in Path("research/recovery_bridge").glob("*.py"):
            sources[path.as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
        report = dict(schema="owned-recovery-bridge-synthetic/1", phases=phases, sources=sources,
            screen=screen(phases), checks=dict(production_parity_closes=sum(PHASES)+len(PHASES)*13*120,
            core_restart_pairs=len(PHASES)*13*len(CUTS), account_and_controller_restart_pairs_each=len(PHASES)*13*len(CUTS)*3,
            daily_accounting_pairs=len(PHASES)*13*120*3, production_constants_unchanged=True),
            artifacts={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in args.output.glob("*.json.gz")})
        (args.output/"summary.json").write_text(json.dumps(report, indent=2)+"\n", encoding="utf-8")
        print(json.dumps(report["screen"]), flush=True)


if __name__ == "__main__":
    main()
