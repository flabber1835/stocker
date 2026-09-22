"""Independent price regeneration, ownership and P&L verification."""
import argparse
from decimal import Decimal as D
import gzip
import hashlib
import json
from pathlib import Path
import tempfile

from .market import multipliers
from .sources import load, source


def reconcile(row, prior_marks, base_opens):
    prices = row["prices"]
    attribution = {}
    for name, account in row["accounts"].items():
        before, after, execution = (account[k] for k in ("before","after","execution"))
        cash = D(before["cash"])
        q = {s:D(v) for s,v in before["shares"].items()}
        prior_value = cash+sum((v*prior_marks[s] for s,v in q.items()),D(0))
        overnight = sum((v*(D(prices[s]["open"])-prior_marks[s]) for s,v in q.items()),D(0))
        shock = sum((v*(D(prices[s]["open"])-base_opens[s]) for s,v in q.items()),D(0))
        open_value = cash+sum((v*D(prices[s]["open"]) for s,v in q.items()),D(0))
        assert abs(open_value-D(str(execution["opening_nav"]))) < D("1e-9")
        fees = D(0)
        for sid, qty, fill in execution["trades"]:
            qty, fill = D(qty), D(fill)
            assert fill == D(prices[sid]["open"]), "fill must use actual stressed open"
            fee = abs(qty*fill)*D(".001")
            cash -= qty*fill+fee
            fees += fee
            q[sid] = q.get(sid,D(0))+qty
        assert abs(cash-D(after["cash"])) < D("1e-18")
        assert {s:v for s,v in q.items() if v} == {s:D(v) for s,v in after["shares"].items()}
        assert abs(D(after["fees"])-D(before["fees"])-fees) < D("1e-18")
        intraday = sum((v*(D(prices[s]["close"])-D(prices[s]["open"]))) for s,v in q.items())
        close_value = cash+sum((v*D(prices[s]["close"]) for s,v in q.items()),D(0))
        assert abs(close_value-D(account["close_nav"])) < D("1e-18")
        assert abs(close_value-(prior_value+overnight+intraday-fees)) < D("1e-18"), "ownership P&L identity"
        attribution[name] = dict(overnight=str(overnight), additional_shock_loss=str(shock),
                                intraday=str(intraday), fees=str(fees))
    return attribution


def check_timing(previous, row):
    for name, account in row["accounts"].items():
        assert account["source_session"] == previous["session"]
        assert account["before"] == previous["accounts"][name]["after"]
        assert account["execution"]["target"] == previous["decisions"][name]["target"], "same-close allocation"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root",type=Path)
    args = parser.parse_args()
    report = json.loads((args.root/"summary.json").read_text())
    attribution, checked, timing_fault = {}, 0, False
    with tempfile.TemporaryDirectory(prefix="recovery-risk-audit-") as temp:
        harness,helpers,_ = load(temp)
        pipeline = helpers[0]
        original = pipeline.factors
        pipeline.factors = lambda c,d,s,h: harness.factors(original,c,d,s,h)
        for name, summary in report["cases"].items():
            phase, remainder = name.split("-",1)
            prefix, mode = remainder.rsplit("-",1)
            path = args.root/f"{name}.json.gz"
            assert hashlib.sha256(path.read_bytes()).hexdigest() == report["artifacts"][path.name]
            rows = json.loads(gzip.decompress(path.read_bytes()))["records"]
            retained = json.loads(gzip.decompress(source(f"audit/owned-recovery-bridge/phase-{phase}-{prefix}.json.gz")))
            initial = set(retained["records"][0]["holding_quantities"])
            pipeline.FORMATION = int(phase)
            market = pipeline.Market()
            for _ in range(pipeline.WARMUP+int(phase)):
                market.advance()
            prior_marks = {s:D(str(p)) for s,p in market.prices.items()} | {"SYNTHETIC:BILL":D(100)}
            assert len(rows) == 120 and [r["day"] for r in rows] == list(range(120))
            event = summary["event_day"]
            assert event == summary["first_bridge"]+2
            details = {}
            for i,row in enumerate(rows):
                base = market.advance(prefix,i,initial)
                assert base.session == row["session"]
                stock,spy = multipliers(mode,i,event,market.meta,summary["event_holdings"])
                base_opens = {b.security_id:D(str(b.raw_open)) for b in base.bars} | {"SYNTHETIC:BILL":D(100)}
                for bar in base.bars:
                    factor = stock.get(bar.security_id,1.)
                    expected = dict(open=str(D(str(bar.raw_open*factor))),close=str(D(str(bar.raw_close*factor))))
                    assert row["prices"][bar.security_id] == expected, "price path mismatch"
                    market.prices[bar.security_id] *= factor
                market.spy[-1] *= spy
                spy20 = market.spy[-1]/market.spy[-21]-1
                assert abs(row["observation"]["spy_r20"]-spy20) < 1e-12
                if i:
                    check_timing(rows[i-1],row)
                result = reconcile(row,prior_marks,base_opens)
                if stock:
                    details[str(i)] = result
                if i == event and mode != "control":
                    assert D(result["bridge"]["additional_shock_loss"]) < 0, "shock must hit preexisting stock ownership"
                prior_marks = {s:D(p["close"]) for s,p in row["prices"].items()}
                checked += len(row["accounts"])
                if i and row["decisions"]["bridge"]["target"] != rows[i-1]["decisions"]["bridge"]["target"]:
                    fault = json.loads(json.dumps(row))
                    fault["accounts"]["bridge"]["execution"]["target"] = row["decisions"]["bridge"]["target"]
                    try:
                        check_timing(rows[i-1],fault)
                    except AssertionError as exc:
                        assert str(exc) == "same-close allocation"
                        timing_fault = True
                    else:
                        raise AssertionError("same-close fault survived")
            event_trace = {}
            for i in range(event-2,min(event+12,len(rows))):
                r = rows[i]
                event_trace[str(i)] = dict(held=r["held"],stock_fraction=r["stock_fraction"],
                    damage=r["observation"]["damaged_breadth"], green=r["observation"]["green_breadth"],
                    r20=r["observation"]["shadow_r20"],native=r["native_multiplier"],
                    recovery=r["recovery_reason"],targets={k:v["target"] for k,v in r["decisions"].items()})
            attribution[name] = dict(stress_days=details,event_trace=event_trace)
    assert checked == 3840 and timing_fault
    output = dict(account_days=checked,causal_execution_fault_killed=timing_fault,attribution=attribution)
    (args.root/"independent-audit.json").write_text(json.dumps(output,indent=2)+"\n",encoding="utf-8",newline="\n")
    print(json.dumps(dict(account_days=checked,causal_execution_fault_killed=timing_fault,cases=len(attribution))))


if __name__ == "__main__":
    main()
