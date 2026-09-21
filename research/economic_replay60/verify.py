"""Read-only independent arithmetic and checkpoint portfolio checks (no replay)."""
import argparse
import csv
from datetime import date
from decimal import Decimal, localcontext
import gzip
import hashlib
import json
from pathlib import Path
import zipfile

D = Decimal
START = "2006-07-31"


def rows(path):
    with gzip.open(path, "rt", newline="") as stream:
        return list(csv.DictReader(stream))


def verify(args):
    daily = []
    for segment in args.segments:
        daily.extend(json.loads(line) for line in (segment / "daily.jsonl").read_text().splitlines())
    dates = [row["date"] for row in daily]
    assert dates == sorted(set(dates)), "duplicate or reversed sessions"
    by_date = {row["date"]: row for row in daily}
    end = dates[-1]
    refs = {row["date"]: row for row in rows(args.reference)}
    spy = {row["date"]: D(row["close_to_close_factor"]) for row in rows(args.sfp)
           if row["ticker"] == "SPY" and row["date"] > START}
    base = D(by_date[START]["nav"])
    multiple = D(1)
    max_cagr_error = D(0)
    allocation_differences = []
    previous_nav = None
    for row in daily:
        day = row["date"]
        econ = row["economics"]
        if previous_nav is not None:
            assert abs(D(econ["previous_strategy_nav"]) - previous_nav) < D("1e-15"), day
        previous_nav = D(row["nav"])
        if day < START:
            assert row["comparison"] is None
            continue
        if day > START:
            multiple *= spy[day]
        expected = {"current": D(row["nav"]) / base,
                    "reference": D(refs[day]["nav"]) / D(refs[START]["nav"]),
                    "spy": multiple}
        days = (date.fromisoformat(day) - date.fromisoformat(START)).days
        for name, value in expected.items():
            actual = row["comparison"][name]
            assert abs(D(actual["multiple"]) - value) < D("1e-20"), (day, name, "multiple")
            if days:
                with localcontext() as ctx:
                    ctx.prec = 40
                    cagr = value ** (D("365.2425") / D(days)) - 1
                error = abs(D(str(actual["cagr"])) - cagr)
                max_cagr_error = max(max_cagr_error, error)
                assert error < D("1e-11"), (day, name, "cagr")
            else:
                assert actual["cagr"] is None
        for current, reference in [("held_allocation", "allocation"),
                                    ("pending_allocation", "close_desired")]:
            if abs(D(econ[current]) - D(refs[day][reference])) > D("1e-10"):
                allocation_differences.append({"date": day, "field": current,
                    "current": econ[current], "reference": refs[day][reference]})
    pointer = json.loads((args.segments[-1] / "latest-checkpoint.json").read_text())
    raw = Path(pointer["path"]).read_bytes()
    assert len(raw) == pointer["bytes"]
    assert hashlib.sha256(raw).hexdigest() == pointer["sha256"]
    checkpoint = json.loads(gzip.decompress(raw))
    assert pointer["last_session"] == end, "use completed segments only"
    assert checkpoint["total_sessions"] == len(daily)
    assert D(checkpoint["statistics"]["base"]) == base
    state = checkpoint["state"]
    core = state["wealth_core"]
    held = {episode["security_id"]: episode for episode in core["episodes"].values()}
    marks = {}
    with zipfile.ZipFile(args.archive) as archive:
        with archive.open("cash.csv.gz") as compressed, gzip.open(compressed, "rt") as stream:
            sessions = [r["session"] for r in csv.DictReader(stream)
                        if dates[0] <= r["session"] <= end]
        assert dates == sessions, "missing exchange sessions"
        with archive.open(f"observations-{end[:4]}.csv.gz") as compressed, gzip.open(compressed, "rt") as stream:
            for observation in csv.DictReader(stream):
                if observation["session"] > end:
                    break
                sid = observation["security_id"]
                if observation["session"] == end and sid in held:
                    marks[sid] = D(observation["raw_close"])
    assert set(marks) == set(held), "cannot independently mark every final holding"
    positions = [{"security_id": sid, "ticker": episode["ticker"],
                  "quantity": episode["current_shares"], "raw_close": str(marks[sid]),
                  "value": str(D(str(episode["current_shares"])) * marks[sid])}
                 for sid, episode in held.items()]
    cash = D(str(core["cash"]))
    receivables = sum((D(str(r["amount"])) for r in state["ledger"]["receivables"]), D(0))
    oracle = cash + receivables + sum((D(p["value"]) for p in positions), D(0))
    residual = oracle - D(daily[-1]["core_nav"])
    assert abs(residual) < D("0.000001"), "portfolio does not reconcile"
    binding = checkpoint["binding"]
    for filename, key in [("run.py", "economic_runner"), ("inputs.py", "economic_inputs"),
                          ("classification-intervals.json.gz", "classification_intervals")]:
        assert hashlib.sha256(Path(__file__).with_name(filename).read_bytes()).hexdigest() == binding[key]
    assert hashlib.sha256(args.reference.read_bytes()).hexdigest() == binding["reference"]
    supplements = {r["id"]: r for r in json.loads(args.supplements.read_text())}
    for key, record in checkpoint["applied_supplements"].items():
        assert supplements[key] == record, "applied supplement changed"
    return {"checks": "PASS", "formation_start": dates[0], "measurement_start": START,
            "last_session": end, "sessions": len(daily), "baseline": str(base),
            "first_holding_date": next(r["date"] for r in daily if r["held_count"]),
            "comparison": daily[-1]["comparison"],
            "anchor_2008_09_02": by_date.get("2008-09-02", {}).get("comparison"),
            "maximum_cagr_error": str(max_cagr_error),
            "allocation_differences": allocation_differences,
            "core_oracle": {"cash": str(cash), "receivables": str(receivables),
                            "positions": positions, "nav": str(oracle), "residual": str(residual)},
            "checkpoint": pointer, "applied_supplements": list(checkpoint["applied_supplements"])}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--segments", type=Path, nargs="+", required=True)
    for name in ["reference", "sfp", "archive", "supplements"]:
        parser.add_argument("--" + name, type=Path, required=True)
    result = verify(parser.parse_args())
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
