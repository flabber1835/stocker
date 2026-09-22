"""Independent retained-trace accounting, timing and signal checks."""
import argparse
from decimal import Decimal as D
import gzip
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

from .sources import load
from .scenarios import factors

PREVIOUS_PHASE_STUDY = "b446e7e02f7257c17c4c57cd1c74eefcd1243303"


def check_timing(rows):
    for prior, current in zip(rows, rows[1:]):
        for name, account in current["accounts"].items():
            assert account["source_session"] == prior["session"], "future Core projection"
            assert account["execution"]["target"] == prior["decisions"][name]["target"], "same-close allocation"
            assert account["before"] == prior["accounts"][name]["after"], "account continuity"


def audit_market(rows, market, case, held):
    checked = 0
    for row in rows:
        publication = market.advance(case, row["day"], held)
        assert publication.session == row["session"]
        opens = {b.security_id:D(str(b.raw_open)) for b in publication.bars} | {"SYNTHETIC:BILL":D(100)}
        closes = {b.security_id:D(str(b.raw_close)) for b in publication.bars} | {"SYNTHETIC:BILL":D(100)}
        ratios = {b.security_id:D(str(b.split_ratio)) for b in publication.bars}
        for account in row["accounts"].values():
            before, after, execution = (account[k] for k in ("before", "after", "execution"))
            prior_q = {s:D(q)*ratios.get(s,D(1)) for s,q in before["shares"].items()}
            opening_value = D(before["cash"])+sum((q*opens[s] for s,q in prior_q.items()),D(0))
            assert abs(opening_value-D(str(execution["opening_nav"]))) < D(".000000001")
            cash = D(before["cash"])
            fee = D(0)
            for s,q,p in execution["trades"]:
                assert D(p) == opens[s], "fill price differs from the generated open"
                quantity = D(q)
                cost = abs(quantity)*opens[s]*D(".001")
                cash -= quantity*opens[s]+cost
                fee += cost
                prior_q[s] = prior_q.get(s,D(0))+quantity
            assert abs(cash-D(after["cash"])) < D("1e-18")
            assert {s:q for s,q in prior_q.items() if q} == {s:D(q) for s,q in after["shares"].items()}
            closing_value = cash+sum((q*closes[s] for s,q in prior_q.items()),D(0))
            assert abs(closing_value-D(account["close_nav"])) < D("1e-18"), "independent close valuation"
            intraday_pnl = sum((q*(closes[s]-opens[s]) for s,q in prior_q.items()),D(0))
            assert abs(closing_value-(opening_value-fee+intraday_pnl)) < D("1e-18"), "daily P&L identity"
            checked += 1
    return checked


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    report = json.loads((args.root/"summary.json").read_text())
    checked, cases, faults, legacy_deltas = 0, 0, {}, {}
    with tempfile.TemporaryDirectory(prefix="bridge-audit-") as temp:
        pipeline, _, _, _, _ = load(Path(temp))
        original = pipeline.factors
        pipeline.factors = lambda case, day, sid, held: factors(original, case, day, sid, held)
        for phase, summaries in report["phases"].items():
            pipeline.FORMATION = int(phase)
            old_path = f"audit/economic-results-diagnosis/phase-{phase}.json.gz"
            # Locate the retained artifact from the pinned tree, not a guessed disk copy.
            names = subprocess.check_output(["git", "ls-tree", "-r", "--name-only", PREVIOUS_PHASE_STUDY], text=True).splitlines()
            candidates = [p for p in names if p.endswith(f"/phase-{phase}.json.gz")]
            old = None
            if len(candidates) == 1:
                raw = subprocess.check_output(["git", "show", f"{PREVIOUS_PHASE_STUDY}:{candidates[0]}"])
                old = json.loads(gzip.decompress(raw))
            for case in summaries:
                path = args.root/f"phase-{phase}-{case}.json.gz"
                assert hashlib.sha256(path.read_bytes()).hexdigest() == report["artifacts"][path.name]
                rows = json.loads(gzip.decompress(path.read_bytes()))["records"]
                assert len(rows) == 120 and [r["day"] for r in rows] == list(range(120))
                check_timing(rows)
                market = pipeline.Market()
                for _ in range(pipeline.WARMUP+int(phase)):
                    market.advance()
                # At scenario open the recorded execution holds the prior Core book.
                # For factor membership use the original source book cohort retained
                # in the original phase trace (day zero stops fill only next open).
                held = set(rows[0]["holding_quantities"])
                checked += audit_market(rows, market, case, held)
                if old is not None and case in old["cases"]:
                    old_rows = old["cases"][case]["records"]
                    assert all(a["observation"] == b["observation"] and a["core_multiplier"] == b["core_multiplier"]
                               for a,b in zip(rows, old_rows)), "retained Core/controller parity"
                    legacy_deltas[f"{phase}/{case}"] = dict(
                        previous_current_nav=old["cases"][case]["summary"]["current"]["ending_nav"],
                        causal_current_nav=summaries[case]["current"]["ending_nav"])
                if case == "healthy_split":
                    control = json.loads(gzip.decompress((args.root/f"phase-{phase}-healthy.json.gz").read_bytes()))["records"]
                    assert all(a["observation"] == b["observation"] and a["decisions"] == b["decisions"] for a,b in zip(rows,control))
                for i in range(1,len(rows)):
                    if rows[i]["decisions"]["current"]["target"] != rows[i-1]["decisions"]["current"]["target"]:
                        changed = json.loads(json.dumps(rows[i-1:i+1]))
                        changed[1]["accounts"]["current"]["execution"]["target"] = changed[1]["decisions"]["current"]["target"]
                        try:
                            check_timing(changed)
                        except AssertionError as exc:
                            assert str(exc) == "same-close allocation"
                            faults["same_close_execution"] = True
                        else:
                            raise AssertionError("same-close fault survived")
                        break
                cases += 1
    assert faults.get("same_close_execution")
    result = dict(cases=cases, independent_account_days=checked, timing_faults_killed=faults,
                  original_core_controller_parity_cases=len(legacy_deltas), legacy_account_differences=legacy_deltas,
                  neutral_split_signal_decisions=True)
    (args.root/"independent-audit.json").write_text(json.dumps(result, indent=2)+"\n")
    print(json.dumps({k:v for k,v in result.items() if k != "legacy_account_differences"}))


if __name__ == "__main__":
    main()
