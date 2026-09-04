#!/usr/bin/env python3
"""Audit date-span identity coverage for the S&P 500 PIT universe.

Stage-3 alias hits are diagnostic until their actual SEP overlap, together with
direct causal bindings, covers the tradable membership interval. This module
measures full/partial/no-coverage intervals and emits a finite residual worklist.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
from collections import Counter
from datetime import date, timedelta
from pathlib import Path
from typing import Iterable, Mapping, Sequence

SCHEMA = "backtester.sp500-pit-coverage-audit/1"
LOCAL_TAPE_START = date(1997, 12, 31)
AUDIT_END_EXCLUSIVE = date(2026, 9, 4)


def _d(value: str, default: date | None = None) -> date:
    text = str(value or "").strip()
    return date.fromisoformat(text) if text else default


def _read_csv(path: Path, gz: bool = False) -> list[dict[str, str]]:
    opener = gzip.open if gz else open
    with opener(path, "rt", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def _write_csv(path: Path, fields: Sequence[str], rows: Iterable[Mapping[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(fields), lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fields})


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _key(row: Mapping[str, str], ticker_field: str = "ticker") -> tuple[str, str, str]:
    return (str(row.get(ticker_field) or ""), str(row.get("member_from") or ""),
            str(row.get("member_until_exclusive") or ""))


def _merge(segments: list[tuple[date, date, str]]) -> list[tuple[date, date]]:
    # Calendar gaps of <=4 days are normal weekends/holidays between observed SEP sessions.
    ordered = sorted((a, b) for a, b, _source in segments if a < b)
    if not ordered:
        return []
    out = [[ordered[0][0], ordered[0][1]]]
    for start, end in ordered[1:]:
        if start <= out[-1][1] + timedelta(days=4):
            out[-1][1] = max(out[-1][1], end)
        else:
            out.append([start, end])
    return [(a, b) for a, b in out]


def audit(*, membership_root: Path, identity_root: Path, alias_root: Path, output: Path) -> dict:
    membership = _read_csv(membership_root / "sp500-membership-intervals.csv.gz", gz=True)
    direct = _read_csv(identity_root / "sp500-security-bindings.csv.gz", gz=True)
    aliases = _read_csv(alias_root / "resolved-aliases.csv.gz", gz=True)
    ambiguous = _read_csv(alias_root / "ambiguous-aliases.csv.gz", gz=True)
    unresolved = _read_csv(alias_root / "unresolved-aliases.csv.gz", gz=True)

    coverage: dict[tuple[str, str, str], list[tuple[date, date, str]]] = {}
    for row in direct:
        start = _d(row["binding_from"])
        end = _d(row.get("binding_until_exclusive", ""), AUDIT_END_EXCLUSIVE)
        coverage.setdefault(_key(row), []).append((start, end, "DIRECT_CAUSAL_IDENTITY"))
    for row in aliases:
        start = _d(row["first_overlap_session"])
        # last_overlap_session is inclusive; next calendar day is an upper bound for
        # the observed alias episode. Weekend gaps are merged separately.
        end = _d(row["last_overlap_session"]) + timedelta(days=1)
        member_end = _d(row.get("member_until_exclusive", ""), AUDIT_END_EXCLUSIVE)
        coverage.setdefault(_key(row, "sp500_ticker"), []).append(
            (start, min(end, member_end), "ALIAS_SEP_OVERLAP")
        )

    ambiguity_keys = {_key(row, "sp500_ticker") for row in ambiguous}
    unresolved_keys = {_key(row, "sp500_ticker") for row in unresolved}
    rows: list[dict[str, object]] = []
    counts = Counter()
    yearly_gap_intervals: dict[int, set[tuple[str, str, str]]] = {}

    for row in membership:
        key = _key(row)
        member_start = _d(row["member_from"])
        member_end = _d(row.get("member_until_exclusive", ""), AUDIT_END_EXCLUSIVE)
        if member_end <= LOCAL_TAPE_START:
            counts["pre_tape_intervals"] += 1
            continue
        target_start = max(member_start, LOCAL_TAPE_START)
        merged = _merge(coverage.get(key, []))
        cursor = target_start
        gaps: list[tuple[date, date]] = []
        for start, end in merged:
            if end <= target_start or start >= member_end:
                continue
            start = max(start, target_start)
            end = min(end, member_end)
            if start > cursor:
                gaps.append((cursor, start))
            cursor = max(cursor, end)
        if cursor < member_end:
            gaps.append((cursor, member_end))

        if not gaps:
            disposition = "FULLY_COVERED"
        elif merged:
            disposition = "PARTIAL_COVERAGE"
        else:
            disposition = "NO_COVERAGE"
        counts[disposition] += 1
        if gaps:
            for a, b in gaps:
                for year in range(a.year, b.year + 1):
                    ys = date(year, 1, 1)
                    ye = date(year + 1, 1, 1)
                    if a < ye and b > ys:
                        yearly_gap_intervals.setdefault(year, set()).add(key)
            rows.append({
                "ticker": key[0],
                "member_from": key[1],
                "member_until_exclusive": key[2],
                "membership_confidence": row.get("confidence", ""),
                "coverage_disposition": disposition,
                "gap_ranges": ";".join(f"{a.isoformat()}..{b.isoformat()}" for a, b in gaps),
                "has_stage3_ambiguity": "1" if key in ambiguity_keys else "0",
                "has_stage3_no_candidate": "1" if key in unresolved_keys else "0",
            })

    output.mkdir(parents=True, exist_ok=True)
    worklist = output / "coverage-worklist.csv"
    _write_csv(worklist, [
        "ticker", "member_from", "member_until_exclusive", "membership_confidence",
        "coverage_disposition", "gap_ranges", "has_stage3_ambiguity", "has_stage3_no_candidate",
    ], sorted(rows, key=lambda r: (r["ticker"], r["member_from"])))
    years = output / "yearly-gap-counts.csv"
    _write_csv(years, ["year", "intervals_with_identity_gap"], [
        {"year": year, "intervals_with_identity_gap": len(keys)}
        for year, keys in sorted(yearly_gap_intervals.items())
    ])
    result = {
        "schema": SCHEMA,
        "status": "COVERAGE_AUDIT_COMPLETE",
        "local_tape_start": LOCAL_TAPE_START.isoformat(),
        "audit_end_exclusive": AUDIT_END_EXCLUSIVE.isoformat(),
        "membership_intervals": len(membership),
        "pre_tape_intervals": counts["pre_tape_intervals"],
        "post_tape_fully_covered_intervals": counts["FULLY_COVERED"],
        "post_tape_partial_coverage_intervals": counts["PARTIAL_COVERAGE"],
        "post_tape_no_coverage_intervals": counts["NO_COVERAGE"],
        "post_tape_intervals_with_gap": len(rows),
        "stage3_ambiguous_inputs": len(ambiguous),
        "stage3_unresolved_inputs": len(unresolved),
        "max_yearly_gap_interval_count": max((len(v) for v in yearly_gap_intervals.values()), default=0),
        "max_yearly_gap_years": [
            y for y, v in sorted(yearly_gap_intervals.items())
            if len(v) == max((len(x) for x in yearly_gap_intervals.values()), default=0)
        ],
    }
    summary = output / "coverage-summary.json"
    summary.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    members = [summary, worklist, years]
    (output / "SHA256SUMS.txt").write_text(
        "".join(f"{_sha256(p)}  {p.name}\n" for p in sorted(members)), encoding="utf-8"
    )
    return result


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--membership-root", type=Path, required=True)
    p.add_argument("--identity-root", type=Path, required=True)
    p.add_argument("--alias-root", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    print(json.dumps(audit(**vars(args)), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
