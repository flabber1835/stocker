#!/usr/bin/env python3
"""Filter S&P PIT coverage gaps to actual SPY trading sessions.

Coverage audit gaps are expressed as calendar intervals. This pass removes gaps
that contain no market session in the frozen Sharadar SEP tape. SPY is used only
as a market-session calendar proxy; it does not establish security identity.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
from pathlib import Path
from typing import Iterable, Mapping, Sequence

SCHEMA = "backtester.sp500-pit-trading-gap-filter/1"


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def _write_csv(path: Path, fields: Sequence[str], rows: Iterable[Mapping[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(fields), lineterminator="\n", extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow({k: row.get(k, "") for k in fields})


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _parse_gaps(text: str) -> list[tuple[str, str]]:
    out = []
    for part in str(text or "").split(";"):
        if ".." not in part:
            continue
        a, b = part.split("..", 1)
        if a and b and a < b:
            out.append((a, b))
    return out


def _spy_sessions(sharadar_root: Path, start_year: int, end_year: int) -> set[str]:
    sessions: set[str] = set()
    for year in range(start_year, end_year + 1):
        path = sharadar_root / f"SHARADAR_SEP_{year}.csv.gz"
        if not path.exists():
            continue
        with gzip.open(path, "rt", encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            if not reader.fieldnames or "ticker" not in reader.fieldnames or "date" not in reader.fieldnames:
                raise RuntimeError(f"SEP file missing ticker/date columns: {path}")
            for row in reader:
                if str(row.get("ticker") or "").strip().upper() == "SPY":
                    d = str(row.get("date") or "").strip()
                    if d:
                        sessions.add(d)
    if not sessions:
        raise RuntimeError("no SPY sessions found in frozen SEP tape")
    return sessions


def filter_gaps(*, coverage_root: Path, sharadar_root: Path, output: Path,
                start_year: int = 1997, end_year: int = 2026) -> dict:
    rows = _read_csv(coverage_root / "coverage-worklist.csv")
    sessions = _spy_sessions(sharadar_root, start_year, end_year)
    kept: list[dict[str, object]] = []
    removed: list[dict[str, object]] = []
    total_ranges = 0
    kept_ranges = 0

    for row in rows:
        real_ranges = []
        dropped_ranges = []
        for a, b in _parse_gaps(row.get("gap_ranges", "")):
            total_ranges += 1
            actual = sorted(d for d in sessions if a <= d < b)
            if actual:
                kept_ranges += 1
                real_ranges.append((a, b, actual[0], actual[-1], len(actual)))
            else:
                dropped_ranges.append((a, b))
        if real_ranges:
            out = dict(row)
            out["gap_ranges"] = ";".join(f"{a}..{b}" for a, b, _f, _l, _n in real_ranges)
            out["gap_trading_sessions"] = ";".join(str(n) for _a, _b, _f, _l, n in real_ranges)
            out["first_gap_sessions"] = ";".join(f for _a, _b, f, _l, _n in real_ranges)
            out["last_gap_sessions"] = ";".join(l for _a, _b, _f, l, _n in real_ranges)
            kept.append(out)
        if dropped_ranges:
            removed.append({
                "ticker": row.get("ticker", ""),
                "member_from": row.get("member_from", ""),
                "member_until_exclusive": row.get("member_until_exclusive", ""),
                "removed_gap_ranges": ";".join(f"{a}..{b}" for a, b in dropped_ranges),
                "reason": "NO_SPY_TRADING_SESSION_IN_GAP",
            })

    output.mkdir(parents=True, exist_ok=True)
    work = output / "coverage-worklist.csv"
    _write_csv(work, [
        "ticker", "member_from", "member_until_exclusive", "membership_confidence",
        "coverage_disposition", "gap_ranges", "gap_trading_sessions", "first_gap_sessions",
        "last_gap_sessions", "has_stage3_ambiguity", "has_stage3_no_candidate",
    ], sorted(kept, key=lambda r: (str(r.get("ticker", "")), str(r.get("member_from", "")))))
    removed_path = output / "removed-nontrading-gaps.csv"
    _write_csv(removed_path, [
        "ticker", "member_from", "member_until_exclusive", "removed_gap_ranges", "reason",
    ], sorted(removed, key=lambda r: (str(r.get("ticker", "")), str(r.get("member_from", "")))))
    result = {
        "schema": SCHEMA,
        "status": "TRADING_GAP_FILTER_COMPLETE",
        "input_gap_intervals": len(rows),
        "output_gap_intervals": len(kept),
        "intervals_with_removed_nontrading_gap": len(removed),
        "input_gap_ranges": total_ranges,
        "output_gap_ranges": kept_ranges,
        "removed_nontrading_gap_ranges": total_ranges - kept_ranges,
        "spy_session_start": min(sessions),
        "spy_session_end": max(sessions),
        "spy_session_count": len(sessions),
        "authority": "SPY observations in frozen Sharadar SEP used solely as trading-session calendar",
    }
    summary = output / "trading-gap-summary.json"
    summary.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    members = [work, removed_path, summary]
    (output / "SHA256SUMS.txt").write_text(
        "".join(f"{_sha256(p)}  {p.name}\n" for p in sorted(members)), encoding="utf-8"
    )
    return result


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--coverage-root", type=Path, required=True)
    p.add_argument("--sharadar-root", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--start-year", type=int, default=1997)
    p.add_argument("--end-year", type=int, default=2026)
    args = p.parse_args()
    print(json.dumps(filter_gaps(**vars(args)), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
