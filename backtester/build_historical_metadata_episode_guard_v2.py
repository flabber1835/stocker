#!/usr/bin/env python3
"""Build a full-canonical ticker/security episode guard for reconstruction v2."""
from __future__ import annotations

import argparse
import csv
import gzip
import json
from pathlib import Path

from backtester import historical_metadata_reconstruction_v2 as base

SCHEMA = "backtester.historical-metadata-reconstruction-v2.episode-guard/1"


def build_guard(dataset: Path, output: Path, from_year: int = 2006, through_year: int = 2026) -> dict:
    state: dict[tuple[str, str], dict[str, object]] = {}
    rows_scanned = 0
    for index, path in enumerate(base.observation_files(dataset), 1):
        with gzip.open(path, "rt", encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                session = str(row.get("session") or "")[:10]
                if len(session) < 4:
                    continue
                try:
                    year = int(session[:4])
                except ValueError:
                    continue
                if not (from_year <= year <= through_year):
                    continue
                sid = str(row.get("security_id") or "").strip()
                ticker = base.norm_ticker(row.get("ticker"))
                if not sid or not ticker:
                    continue
                rows_scanned += 1
                key = (sid, ticker)
                rec = state.setdefault(key, {"first": session, "last": session, "ciks": set(), "observations": 0})
                rec["first"] = min(str(rec["first"]), session)
                rec["last"] = max(str(rec["last"]), session)
                rec["observations"] = int(rec["observations"]) + 1
                cik = base.parse_issuer_authority(row.get("issuer_id"))
                if cik:
                    rec["ciks"].add(cik)
        print(f"[EPISODE GUARD] partition={index} {path.name}", flush=True)

    rows = [
        {
            "security_id": sid,
            "ticker": ticker,
            "first_session": rec["first"],
            "last_session": rec["last"],
            "observations": rec["observations"],
            "observed_ciks": ";".join(sorted(rec["ciks"])),
        }
        for (sid, ticker), rec in sorted(state.items())
    ]
    output.mkdir(parents=True, exist_ok=True)
    path = output / "canonical_ticker_episode_guard.csv.gz"
    base.write_gzip_csv(path, [
        "security_id", "ticker", "first_session", "last_session", "observations", "observed_ciks"
    ], rows)
    by_ticker: dict[str, set[str]] = {}
    for row in rows:
        by_ticker.setdefault(str(row["ticker"]), set()).add(str(row["security_id"]))
    collisions = sum(1 for sids in by_ticker.values() if len(sids) > 1)
    summary = {
        "schema": SCHEMA,
        "status": "PASS",
        "rows_scanned": rows_scanned,
        "episode_rows": len(rows),
        "tickers": len(by_ticker),
        "tickers_used_by_multiple_security_ids": collisions,
        "guard_sha256": base.sha256_file(path),
        "prestart_rule": "a pre-episode filing may seed only within the bounded lookback and only if no other canonical security episode for that ticker covers or follows that filing before the candidate starts",
    }
    (output / "episode_guard_coverage.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    base.write_checksums(output)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--canonical-dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--from-year", type=int, default=2006)
    parser.add_argument("--through-year", type=int, default=2026)
    args = parser.parse_args()
    result = build_guard(args.canonical_dataset, args.output, args.from_year, args.through_year)
    print(json.dumps(result, indent=2, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
