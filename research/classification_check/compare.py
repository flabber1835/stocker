"""Compare first fills and independently add cash plus marked holdings."""
import argparse
import csv
from decimal import Decimal
import gzip
import io
import json
from pathlib import Path
import subprocess
import zipfile

from .classifier import FORMATION_END
from .runner import dump

REFERENCE = "2a1bd486241ae524eac395490b135cc79715e497"
COMPOSITION = "research/champion-certification-20y-v1/results/34544522249-1/portfolio-composition.csv.gz"


def main():
    parser = argparse.ArgumentParser()
    for name in ("output", "control", "archive", "repo"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    target = args.output / "comparison.json"
    if target.exists():
        raise ValueError("comparison already exists")
    retained = {r["date"]: r for r in map(json.loads, args.control.read_text().splitlines())}
    control = list(map(json.loads, (args.output / "control-daily.jsonl").read_text().splitlines()))
    mismatches = [(r["date"], key) for r in control for key in ("nav", "core_nav", "held_count", "decision")
                  if r[key] != retained[r["date"]][key]]
    raw = subprocess.check_output(["git", "-C", str(args.repo), "show", REFERENCE + ":" + COMPOSITION])
    ref = [r for r in csv.DictReader(io.StringIO(gzip.decompress(raw).decode()))
           if r["date"] == FORMATION_END]
    reference_shares = {r["ticker"]: Decimal(r["quantity"]) for r in ref if r["bucket"] == "STOCK"}
    reference_nav = Decimal(ref[0]["core_equity"])
    prices = {}
    with zipfile.ZipFile(args.archive) as archive:
        with archive.open("observations-2006.csv.gz") as raw:
            with gzip.GzipFile(fileobj=raw) as binary:
                for row in csv.DictReader(io.TextIOWrapper(binary)):
                    if row["session"] > FORMATION_END:
                        break
                    if row["session"] == FORMATION_END and row["raw_close"]:
                        prices[row["security_id"]] = Decimal(row["raw_close"])
    result = dict(date=FORMATION_END, reference_commit=REFERENCE, reference_nav=str(reference_nav),
                  reference_holdings={t: str(q) for t, q in reference_shares.items()},
                  control_sessions=len(control), control_mismatches=mismatches, scenarios={})
    for mode in ("control", "dates", "seven", "combined"):
        final = json.loads((args.output / (mode + "-final.json")).read_text())
        if final["last_session"] != FORMATION_END:
            raise ValueError("formation incomplete: " + mode)
        positions = final["holdings"].values()
        holdings = {p["ticker"]: Decimal(str(p["current_shares"])) for p in positions}
        cash = Decimal("100000") + sum((Decimal(str(e["cash_delta"])) for e in final["ledger"]["events"]), Decimal(0))
        equity = sum((Decimal(str(p["current_shares"])) * prices[p["security_id"]] for p in positions), Decimal(0))
        fees = sum((Decimal(str(e["fees"])) for e in final["ledger"]["events"]), Decimal(0))
        oracle = cash + equity
        core = Decimal(final["core_nav"])
        if abs(oracle - core) > Decimal("0.000001"):
            raise ValueError("cash plus marked shares does not reconcile: " + mode)
        result["scenarios"][mode] = dict(
            nav=final["nav"], core_nav=final["core_nav"], oracle_nav=str(oracle),
            cash=str(cash), fees=str(fees), reference_nav_delta=str(core - reference_nav),
            matching_reference_positions=sum(holdings.get(t) == q for t, q in reference_shares.items()),
            absent_from_reference=sorted(set(holdings) - set(reference_shares)),
            absent_from_scenario=sorted(set(reference_shares) - set(holdings)),
            holdings={t: str(q) for t, q in holdings.items()})
    dump(target, result)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
