"""Compare retained reference books with completed economic replay segments."""
import argparse
import csv
from decimal import Decimal as D
import gzip
import io
import json
from pathlib import Path
import subprocess

COMMIT = "2a1bd486241ae524eac395490b135cc79715e497"
PREFIX = "research/champion-certification-20y-v1/results/34544522249-1/"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("segments", type=Path, nargs="+")
    args = parser.parse_args()
    daily = [json.loads(line) for segment in args.segments
             for line in (segment / "daily.jsonl").read_text().splitlines()]
    end = daily[-1]["date"]
    raw = subprocess.check_output(["git", "show", COMMIT + ":" + PREFIX + "portfolio-composition.csv.gz"])
    reference = list(csv.DictReader(io.StringIO(gzip.decompress(raw).decode())))
    nav = {row["date"]: D(row["core_equity"]) for row in reference}
    first_holding = next(row["date"] for row in reference if row["bucket"] == "STOCK")
    first_difference = next(({"date": r["date"], "current_core": r["core_nav"],
        "reference_core": str(nav[r["date"]]),
        "difference": str(D(r["core_nav"]) - nav[r["date"]])}
        for r in daily if abs(D(r["core_nav"]) - nav[r["date"]]) > D("0.000001")), None)
    pointer = json.loads((args.segments[-1] / "latest-checkpoint.json").read_text())
    assert pointer["last_session"] == end
    checkpoint = json.loads(gzip.decompress(Path(pointer["path"]).read_bytes()))
    core = checkpoint["state"]["wealth_core"]
    current = {r["security_id"]: r for r in core["episodes"].values()}
    held_ref = {r["security_id"]: r for r in reference if r["date"] == end and r["bucket"] == "STOCK"}
    differences = []
    for sid in sorted(set(current) | set(held_ref)):
        r = held_ref.get(sid, {})
        c = current.get(sid, {})
        cq, rq = D(str(c.get("current_shares", 0))), D(r.get("quantity", "0"))
        if cq != rq:
            differences.append({"security_id": sid, "ticker": c.get("ticker", r.get("ticker")),
                "current_quantity": str(cq), "reference_quantity": str(rq),
                "reference_mark": r.get("mark"), "reference_mark_source": r.get("mark_source"),
                "quantity_gap_at_reference_mark": str((cq-rq)*D(r["mark"])) if r else None})
    snapshots = []
    baseline = next(r for r in daily if r["date"] == "2006-07-31")
    for day in dict.fromkeys(["2006-01-03", first_holding, "2006-07-31", "2006-09-19",
                              "2006-09-20", "2008-09-02", end]):
        r = next(r for r in daily if r["date"] == day)
        snapshots.append({"date": day, "current_core": r["core_nav"],
                          "reference_core": str(nav[day]), "current_controlled": r["nav"]})
    result = {"reference_commit": COMMIT, "last_session": end,
        "reference_first_holding": first_holding, "snapshots": snapshots,
        "first_core_nav_difference": first_difference,
        "current_core_multiple": str(D(daily[-1]["core_nav"]) / D(baseline["core_nav"])),
        "reference_core_multiple": str(nav[end] / nav["2006-07-31"]),
        "current_core_cash": str(core["cash"]),
        "reference_core_cash": [r["reference_value"] for r in reference
                                 if r["date"] == end and r["bucket"] == "CORE_CASH"],
        "quantity_differences": differences,
        "warning": "Quantity/value gaps are composition differences, not isolated causal P&L attribution."}
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
