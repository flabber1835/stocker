#!/usr/bin/env python3
"""Deterministically shard the authoritative V4 residual for external SEC recovery.

This planner consumes only an already-audited unresolved inventory. It never makes
network requests and never admits metadata. The output is directly consumable by
``expand_historical_authority_v4_issuer_safe harvest``.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import gzip
import hashlib
import io
import json
from collections import Counter
from pathlib import Path
from typing import Iterable, Mapping, Sequence

SCHEMA = "backtester.historical-metadata-external-plan-v4/1"
PLAN_FIELDS = [
    "security_id", "ticker", "first_session", "last_session", "bucket",
    "type_unresolved", "sector_unresolved", "issuer_unresolved",
    "authority_before", "search_start", "search_end", "impact",
    "issuer_resolved", "issuer_state", "source_inventory_sha256",
]
VALID_SCOPES = {"all", "known-or-partial", "full", "partial", "none"}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_gzip_csv(path: Path) -> list[dict[str, str]]:
    with gzip.open(path, "rt", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def write_gzip_csv(path: Path, fields: Sequence[str], rows: Iterable[Mapping[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as raw:
        with gzip.GzipFile(filename="", fileobj=raw, mode="wb", compresslevel=9, mtime=0) as gz:
            with io.TextIOWrapper(gz, encoding="utf-8", newline="") as text:
                writer = csv.DictWriter(text, fieldnames=list(fields), extrasaction="ignore", lineterminator="\n")
                writer.writeheader()
                for row in rows:
                    writer.writerow({field: row.get(field, "") for field in fields})


def _int(row: Mapping[str, object], key: str) -> int:
    try:
        return int(row.get(key) or 0)
    except (TypeError, ValueError):
        return 0


def authority_before(row: Mapping[str, object]) -> str:
    dates: list[str] = []
    if _int(row, "type_unresolved") and row.get("type_first"):
        dates.append(str(row["type_first"])[:10])
    if _int(row, "sector_unresolved") and row.get("sector_first"):
        dates.append(str(row["sector_first"])[:10])
    if not dates:
        raise ValueError(f"unresolved episode lacks causal boundary: {row.get('security_id')}")
    return min(dates)


def issuer_state(row: Mapping[str, object]) -> str:
    unresolved = _int(row, "issuer_unresolved")
    resolved = _int(row, "issuer_resolved")
    if unresolved == 0:
        return "FULL_CAUSAL_IDENTITY"
    if resolved > 0:
        return "PARTIAL_CAUSAL_IDENTITY"
    return "NO_CAUSAL_IDENTITY"


def _scope_accepts(state: str, scope: str) -> bool:
    if scope == "all":
        return True
    if scope == "known-or-partial":
        return state in {"FULL_CAUSAL_IDENTITY", "PARTIAL_CAUSAL_IDENTITY"}
    if scope == "full":
        return state == "FULL_CAUSAL_IDENTITY"
    if scope == "partial":
        return state == "PARTIAL_CAUSAL_IDENTITY"
    if scope == "none":
        return state == "NO_CAUSAL_IDENTITY"
    raise ValueError(f"unknown identity scope: {scope}")


def build_plan(
    inventory: Path,
    output: Path,
    *,
    identity_scope: str = "known-or-partial",
    shard_index: int = 0,
    shard_count: int = 1,
    search_floor: str = "2001-01-01",
    limit: int = 0,
) -> dict[str, object]:
    if identity_scope not in VALID_SCOPES:
        raise ValueError(f"identity_scope must be one of {sorted(VALID_SCOPES)}")
    if shard_count < 1 or not 0 <= shard_index < shard_count:
        raise ValueError("invalid shard index/count")
    dt.date.fromisoformat(search_floor)

    source_sha = sha256_file(inventory)
    source_rows = read_gzip_csv(inventory)
    states = Counter(issuer_state(row) for row in source_rows)
    cohort = []
    for source in source_rows:
        state = issuer_state(source)
        if not _scope_accepts(state, identity_scope):
            continue
        boundary = authority_before(source)
        impact = _int(source, "type_unresolved") + _int(source, "sector_unresolved") + _int(source, "issuer_unresolved")
        cohort.append({
            "security_id": str(source.get("security_id") or ""),
            "ticker": str(source.get("ticker") or "").strip().upper(),
            "first_session": str(source.get("first_session") or "")[:10],
            "last_session": str(source.get("last_session") or "")[:10],
            "bucket": str(source.get("bucket") or ""),
            "type_unresolved": _int(source, "type_unresolved"),
            "sector_unresolved": _int(source, "sector_unresolved"),
            "issuer_unresolved": _int(source, "issuer_unresolved"),
            "authority_before": boundary,
            "search_start": search_floor,
            "search_end": (dt.date.fromisoformat(boundary) - dt.timedelta(days=1)).isoformat(),
            "impact": impact,
            "issuer_resolved": _int(source, "issuer_resolved"),
            "issuer_state": state,
            "source_inventory_sha256": source_sha,
        })

    # High-impact ordering followed by round-robin assignment gives deterministic,
    # approximately balanced shards without splitting any security episode.
    cohort.sort(key=lambda r: (-int(r["impact"]), str(r["ticker"]), str(r["security_id"])))
    selected = [row for rank, row in enumerate(cohort) if rank % shard_count == shard_index]
    if limit > 0:
        selected = selected[:limit]
    selected.sort(key=lambda r: (str(r["ticker"]), str(r["security_id"])))

    output.mkdir(parents=True, exist_ok=True)
    plan_path = output / "plan.csv.gz"
    write_gzip_csv(plan_path, PLAN_FIELDS, selected)
    summary = {
        "schema": SCHEMA,
        "status": "PASS",
        "role": "candidate-only external SEC plan; no network; no admission",
        "source_inventory": inventory.name,
        "source_inventory_sha256": source_sha,
        "inventory_rows": len(source_rows),
        "inventory_identity_states": dict(states),
        "identity_scope": identity_scope,
        "cohort_rows": len(cohort),
        "shard_index": shard_index,
        "shard_count": shard_count,
        "planned_rows": len(selected),
        "unique_security_ids": len({str(row["security_id"]) for row in selected}),
        "unique_tickers": len({str(row["ticker"]) for row in selected}),
        "search_floor": search_floor,
        "strict_prior_rule": "filing_date < earliest unresolved canonical observation",
        "plan_sha256": sha256_file(plan_path),
    }
    (output / "plan_summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    checksum_lines = []
    for path in sorted(p for p in output.iterdir() if p.is_file() and p.name != "SHA256SUMS.txt"):
        checksum_lines.append(f"{sha256_file(path)}  {path.name}")
    (output / "SHA256SUMS.txt").write_text("\n".join(checksum_lines) + "\n", encoding="utf-8")
    return summary


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--identity-scope", choices=sorted(VALID_SCOPES), default="known-or-partial")
    parser.add_argument("--shard-index", type=int, default=0)
    parser.add_argument("--shard-count", type=int, default=1)
    parser.add_argument("--search-floor", default="2001-01-01")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args(argv)
    result = build_plan(
        args.inventory, args.output,
        identity_scope=args.identity_scope,
        shard_index=args.shard_index,
        shard_count=args.shard_count,
        search_floor=args.search_floor,
        limit=args.limit,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
