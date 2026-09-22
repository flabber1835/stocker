"""Eight frozen production-book paths with actual exposure before stress."""
import argparse
import copy
from decimal import Decimal as D
import gzip
import hashlib
import json
from pathlib import Path
import tempfile

from .model import probe
from .market import MODES, apply_opening_loss, multipliers
from .sources import load, source, BRIDGE

PREFIXES = ((40, "owned_recovery"), (120, "leaders_recovery"))
NAMES = ("current", "owned55", "bridge", "sign_bridge")


def constructors(harness, helpers):
    _, parameters, _, owned, _ = helpers
    makers = harness.factories(parameters, owned)
    makers["sign_bridge"] = lambda: harness.RecoveryBridge(owned.Owned55(probe(parameters)))
    return makers


def run_case(prefix, mode, origin, harness, helpers):
    from sentinel.core.kernel import advance_session
    from sentinel.core.session import SessionState
    from research.impedance.pipeline_diagnostics import measure
    pipeline, parameters, accounting, _, _ = helpers
    config, identity, origin_state, origin_market, formation = origin
    state = SessionState.from_dict(origin_state.to_dict())
    market = copy.deepcopy(origin_market)
    makers = constructors(harness, helpers)
    controllers = {name:maker() for name,maker in makers.items()}
    for row in formation:
        decisions = {name:c.step(row) for name,c in controllers.items()}
        parameters.assert_baseline(row, decisions["current"], controllers["current"])
    targets = {name:d["target"] for name,d in decisions.items()}
    accounts = {name:accounting.Account() for name in NAMES}
    marks = {s:D(str(p)) for s,p in market.prices.items()} | {accounting.BILL:D(100)}
    for name, account in accounts.items():
        account.rebalance(state, marks, targets[name])
    initial_held = {e["security_id"] for e in state.wealth_core["episodes"].values()}
    first_bridge = event_day = None
    event_holdings, records, cuts = set(), [], []
    labels = formation[-1]["labels"]
    for day in range(pipeline.LENGTH):
        previous = state
        base = market.advance(prefix, day, initial_held)
        if day == event_day:
            event_holdings = {e["security_id"] for e in previous.wealth_core["episodes"].values()}
        factors, spy_factor = multipliers(mode, day, event_day, market.meta, event_holdings)
        publication = apply_opening_loss(base, market, factors, spy_factor)
        opens = {b.security_id:D(str(b.raw_open)) for b in publication.bars} | {accounting.BILL:D(100)}
        closes = {b.security_id:D(str(b.raw_close)) for b in publication.bars} | {accounting.BILL:D(100)}
        view = harness.projection_view(previous, publication.bars)
        account_rows = {}
        for name, account in accounts.items():
            before = account.snapshot()
            account.split(publication.bars)
            execution = account.rebalance(view, opens, targets[name])
            after = account.snapshot()
            harness.reconcile(before, after, execution, publication.bars)
            account_rows[name] = dict(before=before, after=after, execution=execution,
                source_session=previous.last_processed_session, close_nav=str(account.nav(closes)))
        state = advance_session(previous, publication, controller_config=config, strategy_identity=identity)
        row = measure(state, publication, labels)
        labels = row["labels"]
        before_controllers = {name:c.snapshot() for name,c in controllers.items()}
        decisions = {name:c.step(row) for name,c in controllers.items()}
        parameters.assert_baseline(row, decisions["current"], controllers["current"])
        assert decisions["bridge"]["owned"] == decisions["owned55"]
        assert decisions["owned55"]["base"] == decisions["current"]
        assert controllers["sign_bridge"].owned.base.native.snapshot() == controllers["current"].native.snapshot()
        assert all(0 <= d["target"] <= decisions["current"]["native"] <= 1 for d in decisions.values())
        if first_bridge is None and decisions["bridge"]["target"] > decisions["owned55"]["target"]:
            first_bridge, event_day = day, day+2
        changed = any(d["target"] != targets[name] for name,d in decisions.items())
        relative = event_day is not None and day in (event_day-2,event_day-1,event_day,event_day+1,event_day+10)
        if day in (0,7,19,31,45,69,119) or changed or relative:
            restored = SessionState.from_dict(json.loads(json.dumps(previous.to_dict())))
            assert advance_session(restored, publication, controller_config=config, strategy_identity=identity).state_hash == state.state_hash
            for name in NAMES:
                controller = makers[name]()
                controller.restore(json.loads(json.dumps(before_controllers[name])))
                assert controller.step(row) == decisions[name]
                assert controller.snapshot() == controllers[name].snapshot()
                other = accounting.Account.restore(json.loads(json.dumps(account_rows[name]["before"])))
                other.split(publication.bars)
                assert other.rebalance(view, opens, targets[name]) == account_rows[name]["execution"]
                assert other.snapshot() == account_rows[name]["after"]
            cuts.append(day)
        row.update(day=day, accounts=account_rows, decisions=decisions, core_state_hash=state.state_hash,
            prices={sid:dict(open=str(opens[sid]), close=str(closes[sid])) for sid in opens},
            stress=dict(event_day=event_day, first_bridge=first_bridge, holdings=sorted(event_holdings),
                        stock_factors=factors, spy_factor=spy_factor),
            controller_states={name:c.snapshot() for name,c in controllers.items()})
        records.append(row)
        targets = {name:d["target"] for name,d in decisions.items()}
    assert first_bridge is not None and event_day < len(records), "bridge entry must be reached"
    if mode != "control":
        prior_ownership = records[event_day]["accounts"]["bridge"]["before"]["shares"]
        assert any(s != accounting.BILL and D(q)>0 for s,q in prior_ownership.items()), "stress must hit actual bridge stock ownership"
    harness.NAMES = NAMES
    summary = harness.summarize(records, accounts)
    summary["screen_by_candidate"] = {}
    for name in ("bridge", "sign_bridge"):
        candidate, control = summary[name], summary["owned55"]
        loss = candidate["ending_nav"]-control["ending_nav"]
        dd_delta = 100*(candidate["max_drawdown"]-control["max_drawdown"])
        fee = candidate["fees"]-control["fees"]
        summary["screen_by_candidate"][name] = dict(terminal_delta=loss, drawdown_delta_pp=dd_delta, fee_delta=fee,
            passes=loss >= -2000 and dd_delta >= -2 and fee <= 250,
            minimum_interim_delta=min(float(r["accounts"][name]["close_nav"])-float(r["accounts"]["owned55"]["close_nav"]) for r in records))
    summary.update(first_bridge=first_bridge, event_day=event_day, restart_cuts=cuts,
        event_holdings=sorted(event_holdings), holdings_after_20=sorted(records[event_day+20]["holding_quantities"]))
    return dict(summary=summary, records=records)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=False)
    with tempfile.TemporaryDirectory(prefix="recovery-stress-") as temp:
        harness, helpers, hashes = load(temp)
        pipeline, parameters, _, _, _ = helpers
        original = pipeline.factors
        pipeline.factors = lambda case,day,sid,held: harness.factors(original,case,day,sid,held)
        constants = parameters.production_constants()
        summaries = {}
        for phase, prefix in PREFIXES:
            pipeline.FORMATION = phase
            origin = pipeline.make_origin()
            retained_raw = source(f"audit/owned-recovery-bridge/phase-{phase}-{prefix}.json.gz")
            retained = json.loads(gzip.decompress(retained_raw))
            hashes[f"{BRIDGE}:phase-{phase}-{prefix}"] = hashlib.sha256(retained_raw).hexdigest()
            for mode in MODES:
                name = f"{phase}-{prefix}-{mode}"
                result = run_case(prefix,mode,origin,harness,helpers)
                if mode == "control":
                    for current, old in zip(result["records"],retained["records"]):
                        assert current["observation"] == old["observation"]
                        for variant in ("current","owned55","bridge"):
                            assert current["decisions"][variant] == old["decisions"][variant]
                            assert current["accounts"][variant] == old["accounts"][variant]
                summaries[name] = result["summary"]
                (args.output/f"{name}.json.gz").write_bytes(gzip.compress(json.dumps(result,allow_nan=False).encode(),mtime=0))
                print(json.dumps(dict(case=name,first_bridge=result["summary"]["first_bridge"],
                                     screen=result["summary"]["screen_by_candidate"])),flush=True)
        assert parameters.production_constants() == constants
        for directory in ("research/recovery_stress","sentinel/core","sentinel/controller","shared/stock_strategy_shared/wealth_core"):
            for path in Path(directory).glob("*.py"):
                hashes[path.as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
        verdicts = {variant: all(s["screen_by_candidate"][variant]["passes"] for name,s in summaries.items()
                                if not name.endswith("-control")) for variant in ("bridge","sign_bridge")}
        report = dict(schema="entered-recovery-risk/1", cases=summaries, source_sha256=hashes,
            eligible_for_historical_continuation=verdicts,
            checks=dict(parity_sessions=960,account_days=3840,retained_control_account_days=720,
                core_restart_pairs=sum(len(s["restart_cuts"]) for s in summaries.values()),
                controller_account_restart_pairs_each=4*sum(len(s["restart_cuts"]) for s in summaries.values())),
            artifacts={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in args.output.glob("*.json.gz")})
        (args.output/"summary.json").write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8",newline="\n")
        print(json.dumps(verdicts),flush=True)


if __name__ == "__main__":
    main()
