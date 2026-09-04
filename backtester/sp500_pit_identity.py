#!/usr/bin/env python3
"""Bind S&P 500 PIT membership intervals to the canonical causal security IDs."""
from __future__ import annotations

import argparse
import bisect
import csv
import gzip
import hashlib
import io
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from backtester.strict_pit_metadata import (
    CausalIdentityResolver,
    IDENTITY_AUTHORITY,
    IdentityEpisode,
    build_causal_metadata,
)

SCHEMA = "backtester.sp500-pit-identity/1"
BINDING_COLUMNS = (
    "membership_id", "ticker", "member_from", "member_until_exclusive",
    "membership_confidence", "security_id", "identity_episode",
    "identity_first_session", "binding_from", "binding_until_exclusive",
    "binding_status", "identity_authority",
)
WORKLIST_COLUMNS = (
    "membership_id", "ticker", "member_from", "member_until_exclusive",
    "membership_confidence", "reason", "detail",
)


@dataclass(frozen=True)
class SecurityMeta:
    security_id: str
    ticker: str
    category: str | None = None
    permaticker: str | None = None
    related_tickers: tuple[str, ...] = ()
    first_session: str | None = None
    last_session: str | None = None
    exchange: str | None = None
    exchange_authoritative: bool = False


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _membership_id(row: Mapping[str, str]) -> str:
    payload = "\0".join((
        str(row["ticker"]), str(row["member_from"]),
        str(row.get("member_until_exclusive") or ""),
        str(row.get("confidence") or ""),
    )).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:20]


def _read_membership(path: Path) -> list[dict[str, str]]:
    with gzip.open(path, "rt", encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    required = {"ticker", "member_from", "member_until_exclusive", "confidence"}
    fields = set(rows[0]) if rows else set()
    if not rows or not required.issubset(fields):
        raise RuntimeError(f"membership corpus missing required columns: {sorted(required - fields)}")
    return rows


def bind_membership(
    membership_rows: Sequence[Mapping[str, str]],
    resolver: CausalIdentityResolver,
) -> tuple[list[dict[str, str]], list[dict[str, str]], dict[str, int]]:
    bindings: list[dict[str, str]] = []
    worklist: list[dict[str, str]] = []
    counts = {
        "fully_bound_intervals": 0,
        "prefix_unbound_intervals": 0,
        "unresolved_intervals": 0,
        "multi_episode_intervals": 0,
    }

    for row in membership_rows:
        ticker = str(row["ticker"])
        member_from = str(row["member_from"])
        member_until = str(row.get("member_until_exclusive") or "")
        confidence = str(row.get("confidence") or "")
        membership_id = _membership_id(row)
        episodes = tuple(resolver.episodes.get(ticker, ()))
        starts = tuple(ep.first_session for ep in episodes)

        if not episodes:
            counts["unresolved_intervals"] += 1
            worklist.append({
                "membership_id": membership_id,
                "ticker": ticker,
                "member_from": member_from,
                "member_until_exclusive": member_until,
                "membership_confidence": confidence,
                "reason": "NO_CAUSAL_IDENTITY",
                "detail": "ticker absent from the local historical SEP identity domain",
            })
            continue

        index = bisect.bisect_right(starts, member_from) - 1
        prefix_unbound = False
        if index < 0:
            first = starts[0]
            if member_until and first >= member_until:
                counts["unresolved_intervals"] += 1
                worklist.append({
                    "membership_id": membership_id,
                    "ticker": ticker,
                    "member_from": member_from,
                    "member_until_exclusive": member_until,
                    "membership_confidence": confidence,
                    "reason": "NO_CAUSAL_IDENTITY_DURING_MEMBERSHIP",
                    "detail": f"first local SEP identity session is {first}",
                })
                continue
            index = 0
            prefix_unbound = True
            counts["prefix_unbound_intervals"] += 1
            worklist.append({
                "membership_id": membership_id,
                "ticker": ticker,
                "member_from": member_from,
                "member_until_exclusive": member_until,
                "membership_confidence": confidence,
                "reason": "MEMBERSHIP_PRECEDES_LOCAL_SEP_TAPE",
                "detail": f"binding begins at first local SEP identity session {first}",
            })

        applicable: list[IdentityEpisode] = []
        for ep in episodes[index:]:
            if member_until and ep.first_session >= member_until:
                break
            if ep.first_session < member_from and applicable:
                continue
            applicable.append(ep)
        if not applicable:
            applicable = [episodes[index]]

        if len(applicable) > 1:
            counts["multi_episode_intervals"] += 1
            worklist.append({
                "membership_id": membership_id,
                "ticker": ticker,
                "member_from": member_from,
                "member_until_exclusive": member_until,
                "membership_confidence": confidence,
                "reason": "MULTIPLE_CAUSAL_SECURITY_EPISODES",
                "detail": ";".join(f"{ep.episode}:{ep.first_session}:{ep.sid}" for ep in applicable),
            })

        for pos, ep in enumerate(applicable):
            binding_from = max(member_from, ep.first_session)
            next_start = applicable[pos + 1].first_session if pos + 1 < len(applicable) else ""
            candidates = [x for x in (member_until, next_start) if x]
            binding_until = min(candidates) if candidates else ""
            status = "PREFIX_UNBOUND_THEN_CAUSAL_IDENTITY" if prefix_unbound and pos == 0 else "CAUSAL_IDENTITY_BOUND"
            bindings.append({
                "membership_id": membership_id,
                "ticker": ticker,
                "member_from": member_from,
                "member_until_exclusive": member_until,
                "membership_confidence": confidence,
                "security_id": str(ep.sid),
                "identity_episode": str(ep.episode),
                "identity_first_session": str(ep.first_session),
                "binding_from": binding_from,
                "binding_until_exclusive": binding_until,
                "binding_status": status,
                "identity_authority": IDENTITY_AUTHORITY,
            })

        if not prefix_unbound:
            counts["fully_bound_intervals"] += 1

    bindings.sort(key=lambda r: (r["ticker"], r["member_from"], r["binding_from"], r["security_id"]))
    worklist.sort(key=lambda r: (r["reason"], r["ticker"], r["member_from"]))
    return bindings, worklist, counts


def _write_gzip(path: Path, columns: Sequence[str], rows: Sequence[Mapping[str, str]]) -> None:
    raw = path.open("wb")
    gz = gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0, compresslevel=6)
    text = io.TextIOWrapper(gz, encoding="utf-8", newline="")
    writer = csv.DictWriter(text, fieldnames=columns, lineterminator="\n", extrasaction="raise")
    writer.writeheader()
    writer.writerows(rows)
    text.flush(); text.detach(); gz.close(); raw.close()


def _write_csv(path: Path, columns: Sequence[str], rows: Sequence[Mapping[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns, lineterminator="\n", extrasaction="raise")
        writer.writeheader(); writer.writerows(rows)


def build(
    *,
    membership_root: Path,
    sharadar_root: Path,
    cik_path: Path,
    output: Path,
    start_year: int = 1997,
    end_year: int = 2026,
) -> dict:
    membership_manifest = json.loads((membership_root / "manifest.json").read_text(encoding="utf-8"))
    membership_path = membership_root / "sp500-membership-intervals.csv.gz"
    expected = membership_manifest["members"][membership_path.name]["sha256"]
    observed = _sha256(membership_path)
    if observed != expected:
        raise RuntimeError(f"S&P membership artifact hash mismatch: {observed} != {expected}")

    membership_rows = _read_membership(membership_path)
    meta, _sectors, resolver, _canonical, identity_audit = build_causal_metadata(
        sharadar_root=sharadar_root,
        cik_path=cik_path,
        SecurityMeta=SecurityMeta,
        start_year=start_year,
        end_year=end_year,
        fail_on_identity_conflict=False,
    )
    bindings, worklist, counts = bind_membership(membership_rows, resolver)

    output.mkdir(parents=True, exist_ok=True)
    binding_path = output / "sp500-security-bindings.csv.gz"
    worklist_path = output / "sp500-identity-worklist.csv"
    _write_gzip(binding_path, BINDING_COLUMNS, bindings)
    _write_csv(worklist_path, WORKLIST_COLUMNS, worklist)

    reason_counts: dict[str, int] = {}
    for row in worklist:
        reason = row["reason"]
        reason_counts[reason] = reason_counts.get(reason, 0) + 1
    identity_starts = [ep.first_session for eps in resolver.episodes.values() for ep in eps]
    summary = {
        "schema": SCHEMA,
        "status": "IDENTITY_DIAGNOSTIC_COMPLETE",
        "membership_dataset_hash": membership_manifest["dataset_hash"],
        "membership_intervals": len(membership_rows),
        "binding_rows": len(bindings),
        "bound_security_ids": len({row["security_id"] for row in bindings}),
        "identity_domain_security_ids": len(meta),
        "identity_domain_tickers": len(resolver.episodes),
        "local_identity_start": min(identity_starts) if identity_starts else None,
        "local_identity_end_year": end_year,
        **counts,
        "worklist_rows": len(worklist),
        "worklist_reason_counts": dict(sorted(reason_counts.items())),
        "blocking_identity_conflicts": int(identity_audit.get("blocking_identity_conflicts", 0)),
        "identity_audit": identity_audit,
    }
    summary_path = output / "identity-summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    members = [binding_path, worklist_path, summary_path]
    (output / "SHA256SUMS.txt").write_text(
        "".join(f"{_sha256(path)}  {path.name}\n" for path in members),
        encoding="utf-8",
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--membership-root", required=True, type=Path)
    parser.add_argument("--sharadar-root", default=Path("sharadar"), type=Path)
    parser.add_argument("--cik-path", default=Path("research/sentinel-fastgate/pit-evidence/generated/sec_cik_change_events.csv.gz"), type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--start-year", type=int, default=1997)
    parser.add_argument("--end-year", type=int, default=2026)
    args = parser.parse_args()
    summary = build(
        membership_root=args.membership_root,
        sharadar_root=args.sharadar_root,
        cik_path=args.cik_path,
        output=args.output,
        start_year=args.start_year,
        end_year=args.end_year,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
