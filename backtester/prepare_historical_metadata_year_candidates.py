#!/usr/bin/env python3
"""Prepare small per-year candidate files for parallel historical metadata harvests."""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import backtester.reconstruct_historical_metadata_2006 as base


def write_gzip_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, compresslevel=9, mtime=0) as gz:
            import io
            with io.TextIOWrapper(gz, encoding="utf-8", newline="") as text:
                writer = csv.DictWriter(text, fieldnames=fieldnames, lineterminator="\n")
                writer.writeheader()
                writer.writerows(rows)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--canonical-dataset", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--from-year", type=int, default=2007)
    p.add_argument("--through-year", type=int, default=2026)
    args = p.parse_args()

    years = set(range(args.from_year, args.through_year + 1))
    state: dict[int, dict[tuple[str, str], dict]] = {y: {} for y in years}
    session_rows: dict[int, int] = defaultdict(int)
    sessions: dict[int, set[str]] = defaultdict(set)

    files = base.observation_files(args.canonical_dataset)
    print(f"[PREP] observation_partitions={len(files)} years={args.from_year}-{args.through_year}", flush=True)
    for file_index, path in enumerate(files, 1):
        with gzip.open(path, "rt", encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                session = row.get("session", "")
                if len(session) < 4:
                    continue
                try:
                    year = int(session[:4])
                except ValueError:
                    continue
                if year not in years:
                    continue
                session_rows[year] += 1
                sessions[year].add(session)
                ticker = base.norm_ticker(row.get("ticker", ""))
                sid = (row.get("security_id") or "").strip()
                if not ticker or not sid:
                    continue
                rec = state[year].setdefault((sid, ticker), {"obs": 0, "unknown": 0, "sector": 0, "ciks": set()})
                rec["obs"] += 1
                stype = (row.get("security_type") or "").strip().lower()
                if not stype or stype == "unknown":
                    rec["unknown"] += 1
                if not (row.get("sic") or "").strip() or not (row.get("ff12") or "").strip():
                    rec["sector"] += 1
                cik = base.norm_cik(row.get("issuer_id", ""))
                if cik:
                    rec["ciks"].add(cik)
        print(f"[PREP] partition={file_index}/{len(files)} file={path.name}", flush=True)

    args.output.mkdir(parents=True, exist_ok=True)
    coverage: dict[str, dict] = {}
    fields = [
        "security_id", "ticker", "observations", "unknown_type_observations",
        "missing_sector_observations", "observed_ciks",
    ]
    for year in sorted(years):
        rows: list[dict] = []
        for (sid, ticker), rec in sorted(state[year].items()):
            if not rec["unknown"] and not rec["sector"]:
                continue
            rows.append({
                "security_id": sid,
                "ticker": ticker,
                "observations": rec["obs"],
                "unknown_type_observations": rec["unknown"],
                "missing_sector_observations": rec["sector"],
                "observed_ciks": ";".join(sorted(rec["ciks"])),
            })
        write_gzip_csv(args.output / f"candidates-{year}.csv.gz", fields, rows)
        coverage[str(year)] = {
            "candidate_session_rows": session_rows[year],
            "sessions": len(sessions[year]),
            "candidate_security_episodes": len(state[year]),
            "episodes_needing_type_or_sector_enrichment": len(rows),
            "candidate_tickers": len({r["ticker"] for r in rows}),
            "unknown_type_observations": sum(int(r["unknown_type_observations"]) for r in rows),
            "missing_sector_observations": sum(int(r["missing_sector_observations"]) for r in rows),
        }
        print(
            f"[PREP] year={year} candidates={len(rows)} tickers={coverage[str(year)]['candidate_tickers']} "
            f"unknown_obs={coverage[str(year)]['unknown_type_observations']} "
            f"missing_sector_obs={coverage[str(year)]['missing_sector_observations']}",
            flush=True,
        )

    index = {
        "schema": "backtester.historical-metadata-year-candidates/1",
        "from_year": args.from_year,
        "through_year": args.through_year,
        "years": coverage,
    }
    (args.output / "coverage-index.json").write_text(json.dumps(index, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    files_out = sorted(p for p in args.output.iterdir() if p.is_file() and p.name != "SHA256SUMS.txt")
    sums = [f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}" for p in files_out]
    (args.output / "SHA256SUMS.txt").write_text("\n".join(sums) + "\n", encoding="utf-8")
    print("[PREP] complete", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
