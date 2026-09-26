"""Read-only diagnostic; never changes source admission or runs a strategy."""
import csv
import gzip
import hashlib
import io
import json
from pathlib import Path
import time
import zipfile
import argparse

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--inputs', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
ROOT, OUT = args.inputs, args.output
TARGETS = {"FSNMQ": "750813509120092497", "FCEC": "506347706538298975"}
selected = []
counts = {}
started = time.monotonic()

def consume(stream, label):
    reader = csv.reader(stream)
    columns = next(reader)
    ti, si, di = (columns.index(k) for k in ("ticker", "security_id", "session"))
    n = 0
    for row in reader:
        n += 1
        if row[ti] in TARGETS or row[si] in TARGETS.values():
            selected.append(dict(zip(columns, row)))
    counts[label] = n
    print(json.dumps({"member": label, "rows": n, "selected": len(selected),
                      "elapsed_seconds": round(time.monotonic()-started, 1)}), flush=True)

prefix = ROOT / "pit-prefix-evidence/canonical-2005"
with gzip.open(prefix / "observations-2005.csv.gz", "rt", newline="", encoding="utf8") as f:
    consume(f, "prefix/observations-2005.csv.gz")
with zipfile.ZipFile(ROOT / "pit-source-5bdc6b39.zip") as z:
    manifests = [n for n in z.namelist() if n.endswith("manifest.json")]
    assert len(manifests) == 1
    base = manifests[0].removesuffix("manifest.json")
    for year in range(2006, 2027):
        member = base + f"observations-{year}.csv.gz"
        with z.open(member) as binary, gzip.GzipFile(fileobj=binary) as gz:
            with io.TextIOWrapper(gz, newline="", encoding="utf8") as f:
                consume(f, member)

summary = {}
for ticker, sid in TARGETS.items():
    rows = [r for r in selected if r["security_id"] == sid]
    values = []
    for r in rows:
        try:
            values.append((float(r["raw_close"])*float(r["raw_compatible_volume"]), r["session"]))
        except ValueError:
            pass
    summary[ticker] = dict(security_id=sid, rows=len(rows),
        tickers=sorted({r["ticker"] for r in rows}),
        first=min(r["session"] for r in rows), last=max(r["session"] for r in rows),
        max_daily_dollar_volume=max(values),
        days_at_or_above_5m=sum(v >= 5e6 for v, d in values),
        days_at_or_above_20m=sum(v >= 20e6 for v, d in values))
payload = dict(schema="owned55.split-reachability-diagnostic/1", status="DIAGNOSTIC_ONLY",
    admission_changed=False, strategy_replay_run=False, member_row_counts=counts,
    targets=summary, selected_rows=selected)
path = OUT / "reachability-probe.json"
path.write_text(json.dumps(payload, sort_keys=True, indent=2)+"\n", encoding="utf8")
print(json.dumps(dict(summary=summary, artifact_sha256=hashlib.sha256(path.read_bytes()).hexdigest())), flush=True)
