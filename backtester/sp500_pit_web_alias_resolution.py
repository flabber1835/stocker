#!/usr/bin/env python3
"""Resolve residual S&P PIT identity gaps from bounded web-proven alias evidence.

The evidence file is human/LLM curated, but admission remains mechanical: a row is
accepted only when the candidate ticker has actual frozen SEP observations inside
the declared evidence interval and the causal identity resolver returns a security
ID for the first overlapping session.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from backtester.strict_pit_metadata import _price_dates, build_causal_metadata

SCHEMA = "backtester.sp500-pit-web-alias-resolution/1"


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


def _overlap(a: str, b: str, c: str, d: str) -> tuple[str, str] | None:
    left = max(a, c)
    right = min(b, d)
    return (left, right) if left < right else None


def resolve(*, coverage_root: Path, evidence_path: Path, sharadar_root: Path,
            cik_path: Path, output: Path, start_year: int = 1997, end_year: int = 2026) -> dict:
    gaps = _read_csv(coverage_root / "coverage-worklist.csv")
    evidence = _read_csv(evidence_path)
    price_dates = _price_dates(sharadar_root, start_year, end_year)

    class SecurityMeta:
        def __init__(self, security_id, ticker, category, permaticker, related_tickers,
                     first_session, last_session, exchange, exchange_authoritative):
            self.security_id = security_id
            self.ticker = ticker
            self.first_session = first_session

    _meta, _sectors, resolver, _canonical, audit = build_causal_metadata(
        sharadar_root=sharadar_root,
        cik_path=cik_path,
        SecurityMeta=SecurityMeta,
        start_year=start_year,
        end_year=end_year,
        fail_on_identity_conflict=True,
    )

    by_source: dict[str, list[dict[str, str]]] = {}
    for row in evidence:
        by_source.setdefault(str(row.get("source_ticker") or "").upper(), []).append(row)

    accepted: list[dict[str, object]] = []
    rejected: list[dict[str, object]] = []
    for row in gaps:
        source = str(row.get("ticker") or "").upper()
        for gs, ge in _parse_gaps(row.get("gap_ranges", "")):
            for ev in by_source.get(source, []):
                ev_from = str(ev.get("map_from") or "")
                ev_until = str(ev.get("map_until_exclusive") or "")
                bounded = _overlap(gs, ge, ev_from, ev_until)
                if not bounded:
                    continue
                left, right = bounded
                candidate = str(ev.get("candidate_ticker") or "").upper()
                sessions = [d for d in price_dates.get(candidate, ()) if left <= d < right]
                if not sessions:
                    rejected.append({
                        "source_ticker": source,
                        "gap_from": gs,
                        "gap_until_exclusive": ge,
                        "candidate_ticker": candidate,
                        "bounded_from": left,
                        "bounded_until_exclusive": right,
                        "reason": "NO_SEP_OVERLAP",
                        "evidence_url": ev.get("evidence_url", ""),
                    })
                    continue
                sid = resolver.resolve(candidate, sessions[0])
                if sid is None:
                    rejected.append({
                        "source_ticker": source,
                        "gap_from": gs,
                        "gap_until_exclusive": ge,
                        "candidate_ticker": candidate,
                        "bounded_from": left,
                        "bounded_until_exclusive": right,
                        "reason": "NO_CAUSAL_SECURITY_ID",
                        "evidence_url": ev.get("evidence_url", ""),
                    })
                    continue
                accepted.append({
                    "source_ticker": source,
                    "gap_from": gs,
                    "gap_until_exclusive": ge,
                    "resolved_ticker": candidate,
                    "security_id": sid,
                    "binding_from": sessions[0],
                    "binding_until_exclusive": right,
                    "last_overlap_session": sessions[-1],
                    "evidence_type": ev.get("evidence_type", ""),
                    "evidence_url": ev.get("evidence_url", ""),
                    "evidence_summary": ev.get("evidence_summary", ""),
                    "authority": "WEB_PROVEN_BOUNDED_ALIAS_PLUS_CAUSAL_SEP_OVERLAP",
                })

    # A bounded source/gap interval must not resolve to multiple security IDs.
    grouped: dict[tuple[str, str, str, str, str], set[str]] = {}
    for r in accepted:
        key = (str(r["source_ticker"]), str(r["gap_from"]), str(r["gap_until_exclusive"]),
               str(r["binding_from"]), str(r["binding_until_exclusive"]))
        grouped.setdefault(key, set()).add(str(r["security_id"]))
    conflicts = [k for k, sids in grouped.items() if len(sids) > 1]
    if conflicts:
        raise RuntimeError(f"web alias evidence produced conflicting security IDs: {conflicts[:5]}")

    output.mkdir(parents=True, exist_ok=True)
    accepted_path = output / "accepted-web-aliases.csv"
    rejected_path = output / "rejected-web-aliases.csv"
    _write_csv(accepted_path, [
        "source_ticker", "gap_from", "gap_until_exclusive", "resolved_ticker", "security_id",
        "binding_from", "binding_until_exclusive", "last_overlap_session", "evidence_type",
        "evidence_url", "evidence_summary", "authority",
    ], accepted)
    _write_csv(rejected_path, [
        "source_ticker", "gap_from", "gap_until_exclusive", "candidate_ticker", "bounded_from",
        "bounded_until_exclusive", "reason", "evidence_url",
    ], rejected)
    result = {
        "schema": SCHEMA,
        "status": "WEB_ALIAS_RESOLUTION_COMPLETE",
        "evidence_rows": len(evidence),
        "coverage_gap_intervals": len(gaps),
        "accepted_binding_segments": len(accepted),
        "accepted_source_tickers": len({str(r['source_ticker']) for r in accepted}),
        "rejected_segments": len(rejected),
        "blocking_identity_conflicts": int(audit.get("blocking_identity_conflicts", 0)),
        "web_alias_conflicts": len(conflicts),
    }
    summary = output / "web-alias-summary.json"
    summary.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    members = [accepted_path, rejected_path, summary]
    (output / "SHA256SUMS.txt").write_text(
        "".join(f"{_sha256(p)}  {p.name}\n" for p in sorted(members)), encoding="utf-8"
    )
    return result


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--coverage-root", type=Path, required=True)
    p.add_argument("--evidence-path", type=Path, required=True)
    p.add_argument("--sharadar-root", type=Path, required=True)
    p.add_argument("--cik-path", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--start-year", type=int, default=1997)
    p.add_argument("--end-year", type=int, default=2026)
    args = p.parse_args()
    print(json.dumps(resolve(**vars(args)), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
