"""Reconcile retained cash-merger witnesses with later legal completions.

This is an input transformation, not a replay or source-admission certificate.
"""
from __future__ import annotations

import argparse
import gzip
import json
from pathlib import Path
import zipfile
import csv
import io

from research.bounded_20y.inputs import BASE_ARCHIVE_SHA256, sha256

SOURCE_SUPPLEMENTS_SHA256 = "aac7fd0e9110503f6b32c26ba93e8bbb044b2ada494ba2b8ca88e968dde09aa5"
CHRONOLOGY = Path(__file__).with_name("chronology.json")
RAW_DISPOSITION = "PIT_ACTION_INCOMPLETE:MISSING_CASH_PER_SHARE"


def load_chronology(path: Path = CHRONOLOGY) -> list[dict]:
    rows = json.loads(path.read_text(encoding="utf-8"))
    if len(rows) != 12 or len({r["security_id"] for r in rows}) != len(rows):
        raise ValueError("chronology identities missing or duplicated")
    for row in rows:
        if (row["original_event_session"] >= row["completion_session"]
                or not row["source"].startswith("https://www.sec.gov/")):
            raise ValueError("invalid completion chronology")
    return rows


def repair(raw_rows: list[dict], supplements: list[dict], chronology: list[dict]
           ) -> tuple[list[dict], list[dict], dict]:
    """Return new rows; leave retained inputs untouched and refuse identity drift."""
    raw_rows = list(raw_rows)
    supplements = list(supplements)
    if len({r["id"] for r in supplements}) != len(supplements):
        raise ValueError("duplicate supplement identity")
    corrected = []
    suppress = set()
    seen = set()
    for rule in chronology:
        sid = rule["security_id"]
        if sid in seen:
            raise ValueError("duplicate chronology security")
        seen.add(sid)
        old = rule["original_event_session"]
        match = [r for r in raw_rows if r["security_id"] == sid]
        if len(match) != 1:
            raise ValueError("expected one raw terminal: " + rule["ticker"])
        raw = match[0]
        expected = {"effective_session": old, "security_id": sid,
                    "ticker": rule["ticker"], "kind": "CASH_MERGER",
                    "disposition": RAW_DISPOSITION, "cash_per_share": ""}
        if any(raw.get(k) != v for k, v in expected.items()):
            raise ValueError("raw terminal differs: " + rule["ticker"])
        terms = [r for r in supplements if r["id"] == rule["source_supplement_id"]]
        if len(terms) != 1:
            raise ValueError("expected one source supplement: " + rule["ticker"])
        term = terms[0]
        required = {"security_id": sid, "ticker": rule["ticker"],
                    "kind": "CASH_MERGER", "original_event_session": old,
                    "effective_session": old, "cash_per_share": rule["cash_per_share"]}
        if (any(term.get(k) != v for k, v in required.items())
                or not term.get("sources") or rule["source"] not in term["sources"]):
            raise ValueError("source supplement differs: " + rule["ticker"])
        if any(r["security_id"] == sid and r["id"] != term["id"] for r in supplements):
            raise ValueError("additional supplement for corrected security: " + rule["ticker"])
        suppress.add((old, sid))
        corrected.append({**term,
                          "id": term["id"] + "-stage2-chronology-v1",
                          "effective_session": rule["completion_session"],
                          "disposition": "SOURCE_BACKED_LEGAL_COMPLETION_CLOSE_RECOGNITION",
                          "authority": "SEC_COMPLETION_AND_RETAINED_RAW_WITNESS",
                          "reference": ("Legal completion " + rule["completion_session"]
                                        + "; close recognition; broker credit unproven; "
                                        + rule["source"]),
                          "supersedes_supplement_id": term["id"]})
    repaired_supplements = [r for r in supplements if r["id"] not in
                            {rule["source_supplement_id"] for rule in chronology}] + corrected
    if len(repaired_supplements) != len(supplements):
        raise ValueError("supplement cardinality changed")
    remaining_raw = [r for r in raw_rows if (r["effective_session"], r["security_id"]) not in suppress]
    if len(raw_rows) - len(remaining_raw) != len(chronology):
        raise ValueError("raw terminal suppression count differs")
    # Mirror the retained research adapter for all other supplemented terminals.
    schedule = {(r["effective_session"], r["security_id"]): r for r in remaining_raw}
    if len(schedule) != len(remaining_raw):
        raise ValueError("duplicate raw terminal identity")
    for row in repaired_supplements:
        if row.get("kind") == "SPINOFF":
            continue
        key = (row["effective_session"], row["security_id"])
        if key in schedule and schedule[key].get("cash_per_share"):
            raise ValueError("completed terminal collision: " + row["id"])
        schedule[key] = row
    for rule in chronology:
        sid = rule["security_id"]
        days = [day for day, security in schedule if security == sid]
        if days != [rule["completion_session"]]:
            raise ValueError("corrected terminal is not unique: " + rule["ticker"])
    audit = {"status": "CHRONOLOGY_REPAIRED_RESEARCH_ONLY",
             "corrected_count": len(chronology),
             "suppressed_raw_count": len(suppress),
             "remaining_blockers": ["PLYA_TENDER_ENTITLEMENT", "2005_SPLIT_SOURCE_ADMISSION",
                                    "CASH_CREDIT_AND_PROXY_ECONOMICS"]}
    return list(schedule.values()), repaired_supplements, audit


def export(archive: Path, source: Path, output: Path) -> dict:
    if sha256(archive) != BASE_ARCHIVE_SHA256:
        raise ValueError("retained archive identity differs")
    if sha256(source) != SOURCE_SUPPLEMENTS_SHA256:
        raise ValueError("retained supplements identity differs")
    with zipfile.ZipFile(archive) as z:
        with gzip.open(io.BytesIO(z.read("terminal-events.csv.gz")), "rt", newline="") as stream:
            raw = list(csv.DictReader(stream))
    chronology = load_chronology()
    schedule, supplements, audit = repair(raw, json.loads(source.read_text(encoding="utf-8")), chronology)
    output.mkdir(parents=True, exist_ok=False)
    for name, value in (("terminal-schedule.json", schedule), ("supplements.json", supplements)):
        (output / name).write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    manifest = {**audit, "base_archive_sha256": BASE_ARCHIVE_SHA256,
                "source_supplements_sha256": SOURCE_SUPPLEMENTS_SHA256,
                "chronology_sha256": sha256(CHRONOLOGY),
                "outputs": {name: sha256(output / name) for name in
                            ("terminal-schedule.json", "supplements.json")}}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--supplements", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(export(args.archive, args.supplements, args.output), sort_keys=True))
