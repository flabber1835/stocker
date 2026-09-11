"""Private, indexed vendor truth. This module never imports application code.

The canonical package is immutable. Only the simulated provider reads this
database; the application receives bounded HTTP responses and owns another DB.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
from pathlib import Path
import sqlite3

from . import authority as a


def rows(path):
    with gzip.open(path, "rt", newline="") as source:
        yield from csv.DictReader(source)


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as source:
        for part in iter(lambda: source.read(1024*1024), b""):
            h.update(part)
    return h.hexdigest()


def number(value, default=None):
    if value in (None, "", "nan", "None"):
        return default
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("nonfinite canonical numeric field")
    return result


def validate_package(root):
    manifest = json.loads((root / "manifest.json").read_text())
    assert manifest["status"] == "PASS"
    assert manifest["schema"] == "backtester.canonical-pit-dataset/2"
    assert manifest["window"] == dict(warmup_start=a.WARMUP, measurement_start=a.MEASUREMENT, end=a.END)
    h = hashlib.sha256()
    members = manifest["members"]
    expected = {f"observations-{y}.csv.gz" for y in range(2006, 2027)} | {
        "metadata-timeline.csv.gz", "actions.csv.gz", "terminal-events.csv.gz",
        "cash.csv.gz", "benchmark.csv.gz", "session-hashes.csv"}
    assert set(members) == expected
    for name, item in sorted(members.items()):
        path = root / name
        assert path.stat().st_size == item["bytes"], name
        assert sha(path) == item["sha256"], name
        h.update(f"{name}\0{item['sha256']}\0{item['bytes']}\n".encode())
    assert h.hexdigest() == manifest["dataset_hash"] == a.DATASET_SHA256
    return manifest


def compile_truth(root, output, *, estimate):
    manifest = validate_package(root)
    if output.exists():
        raise ValueError("private truth output already exists")
    db = sqlite3.connect(output)
    db.executescript("""
        PRAGMA journal_mode=OFF;
        CREATE TABLE obs(day TEXT,sid TEXT,ticker TEXT,op REAL,raw REAL,signal REAL,
            volume REAL,raw_volume REAL,split REAL,dividend REAL,
            PRIMARY KEY(day,sid)) WITHOUT ROWID;
        CREATE TABLE meta(day TEXT,sid TEXT,ticker TEXT,body TEXT,
            PRIMARY KEY(day,sid,ticker)) WITHOUT ROWID;
        CREATE TABLE actions(day TEXT,sid TEXT,body TEXT);
        CREATE TABLE terminals(day TEXT,sid TEXT,body TEXT);
        CREATE TABLE reference(day TEXT PRIMARY KEY,spy REAL,gap REAL,intraday REAL,cash_source TEXT);
        CREATE TABLE identity(body TEXT);
    """)
    previous, counts = {}, {}
    for year in range(2006, 2027):
        count = 0
        batch = []
        for r in rows(root / f"observations-{year}.csv.gz"):
            day, sid, ticker = r["session"], r["security_id"], r["ticker"]
            if not a.WARMUP <= day <= a.END:
                raise ValueError("observation outside frozen window")
            batch.append((day, sid, ticker, number(r["raw_open"]), number(r["raw_close"]),
                number(r["signal_close"]), number(r["reported_volume"]),
                number(r["raw_compatible_volume"]), number(r["split_ratio"], 1.),
                number(r["dividend_per_share"], 0.)))
            kind = r["security_type"]
            provenance = r["security_type_source"]
            # The certified scenario estimates only unknown candidates. Unknown
            # non-candidates remain excluded until their admitted interval begins.
            er = estimate.rows.get(sid)
            if kind == "unknown" and er and er["unknown_first_session"] <= day <= er["unknown_last_session"]:
                kind = estimate.peek(sid, day)
                provenance = "reviewed_18_reconstruction"
            meta = dict(table="SEP", permaticker=sid, ticker=ticker,
                category="Domestic Common Stock" if kind == "common" else "Non Common Equity",
                relatedtickers=None, firstpricedate=r["listing_first_session"] or day,
                sector=r["ff12"], exchange=r["exchange"] or None,
                classification_source=provenance, canonical_security_type=r["security_type"],
                metadata_admitted=r["metadata_admitted"])
            key = (sid, ticker)
            if previous.get(key) != meta:
                db.execute("INSERT INTO meta VALUES(?,?,?,?)", (day, sid, ticker, json.dumps(meta, sort_keys=True)))
                previous[key] = meta
            if len(batch) == 10000:
                db.executemany("INSERT INTO obs VALUES(?,?,?,?,?,?,?,?,?,?)", batch)
                batch.clear()
            count += 1
        db.executemany("INSERT INTO obs VALUES(?,?,?,?,?,?,?,?,?,?)", batch)
        assert count == manifest["members"][f"observations-{year}.csv.gz"]["rows"]
        counts[str(year)] = count
        db.commit()
        print(json.dumps(dict(phase="compile", year=year, observations=count)), flush=True)
    for filename, table in (("actions.csv.gz", "actions"), ("terminal-events.csv.gz", "terminals")):
        for r in rows(root / filename):
            db.execute(f"INSERT INTO {table} VALUES(?,?,?)", (r["effective_session"], r["security_id"], json.dumps(r, sort_keys=True)))
    cash = {r["session"]: r for r in rows(root / "cash.csv.gz")}
    for r in rows(root / "benchmark.csv.gz"):
        c = cash[r["session"]]
        db.execute("INSERT INTO reference VALUES(?,?,?,?,?)", (r["session"], float(r["level"]),
            float(c["gap_factor"]), float(c["intraday_factor"]), c["source"]))
    db.executescript("""
        CREATE INDEX obs_sid_day ON obs(sid,day);
        CREATE INDEX meta_sid_day ON meta(sid,ticker,day);
        CREATE INDEX actions_day ON actions(day);
        CREATE INDEX terminals_day ON terminals(day);
    """)
    sessions = [r[0] for r in db.execute("SELECT day FROM reference ORDER BY day")]
    assert len(sessions) == a.OBSERVATIONS and sessions[0] == a.WARMUP and sessions[-1] == a.END
    assert len([d for d in sessions if d >= a.MEASUREMENT]) == a.MEASURED
    identity = dict(schema="full-system-private-truth/1", dataset_sha256=a.DATASET_SHA256,
        observations=counts, sessions=sessions, compiler_sha256=sha(__file__),
        classification=estimate.summary(), vendor_vintages="reconstructed_split_basis_v1",
        pre_inception_cash="declared canonical Treasury proxy", canonical_manifest=manifest)
    db.execute("INSERT INTO identity VALUES(?)", (json.dumps(identity, sort_keys=True),))
    db.commit()
    assert db.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
    db.close()
    output.with_suffix(".json").write_text(json.dumps(identity, indent=2, sort_keys=True) + "\n")
    return identity


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--classification", type=Path, required=True)
    args = parser.parse_args()
    from backtester.research_champion_best_effort_classification import SecurityTypeEstimate
    estimate = SecurityTypeEstimate(args.classification, "reviewed_18",
        args.classification.with_name("champion-reviewed-security-types-v1.csv"))
    compile_truth(args.dataset, args.output, estimate=estimate)
