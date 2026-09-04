#!/usr/bin/env python3
"""Materialize a runnable best-effort S&P 500 point-in-time eligibility tape.

This module intentionally does not claim formal PIT certification.  It combines:
* dated S&P membership intervals,
* direct causal SEP identity bindings,
* uniquely admitted historical ticker aliases with actual SEP overlap,
* bounded web-proven aliases with causal SEP overlap, and
* unique SEC-CIK alias candidates with causal SEP overlap.

A source constituent is eligible on a session only when exactly one approved
security mapping is active and the mapped ticker is actually observed in the
frozen SEP tape on that session.  Ambiguous, conflicting, and unresolved
source/session pairs are explicitly excluded and recorded.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from statistics import median
from typing import Iterable, Mapping, Sequence

SCHEMA = "backtester.sp500-best-effort-universe/1"
STATUS = "BEST_EFFORT_RUNNABLE"
MIN_TICKERS_PER_SESSION = 1000
EXPECTED_MEMBERSHIP_DATASET_HASH = (
    "1981828b71073be4d0fcf4addb37a56c844a29219090eb0c8fbc535d393bdb2d"
)

SEGMENT_FIELDS = (
    "source_ticker", "member_from", "member_until_exclusive", "membership_confidence",
    "resolved_ticker", "security_id", "segment_from", "segment_until_exclusive",
    "authority",
)
ELIGIBILITY_FIELDS = (
    "date", "source_ticker", "resolved_ticker", "security_id",
    "membership_confidence", "authority",
)
EXCLUSION_FIELDS = (
    "date", "source_ticker", "member_from", "member_until_exclusive",
    "membership_confidence", "reason", "detail",
)
CONFLICT_FIELDS = (
    "scope", "source_ticker", "from_date", "until_exclusive", "reason", "detail",
)


@dataclass(frozen=True)
class Membership:
    ticker: str
    start: date
    end: date
    start_text: str
    end_text: str
    confidence: str

    @property
    def key(self) -> tuple[str, str, str]:
        return self.ticker, self.start_text, self.end_text


@dataclass(frozen=True)
class Segment:
    source_ticker: str
    member_from: str
    member_until_exclusive: str
    membership_confidence: str
    resolved_ticker: str
    security_id: str
    start: date
    end: date
    authority: str

    @property
    def membership_key(self) -> tuple[str, str, str]:
        return self.source_ticker, self.member_from, self.member_until_exclusive


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _read_csv(path: Path, *, gz: bool = False) -> list[dict[str, str]]:
    opener = gzip.open if gz else open
    with opener(path, "rt", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def _write_csv(path: Path, fields: Sequence[str], rows: Iterable[Mapping[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(
            fh, fieldnames=list(fields), lineterminator="\n", extrasaction="ignore"
        )
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fields})


def _write_gzip_csv(
    path: Path, fields: Sequence[str], rows: Iterable[Mapping[str, object]]
) -> None:
    raw = path.open("wb")
    gz = gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0, compresslevel=6)
    text = io.TextIOWrapper(gz, encoding="utf-8", newline="")
    writer = csv.DictWriter(
        text, fieldnames=list(fields), lineterminator="\n", extrasaction="ignore"
    )
    writer.writeheader()
    for row in rows:
        writer.writerow({k: row.get(k, "") for k in fields})
    text.flush()
    text.detach()
    gz.close()
    raw.close()


def _d(text: str, default: date | None = None) -> date:
    value = str(text or "").strip()
    if value:
        return date.fromisoformat(value)
    if default is None:
        raise ValueError("empty date without default")
    return default


def _inclusive_end_to_exclusive(text: str) -> date:
    return date.fromisoformat(str(text)) + timedelta(days=1)


def _load_memberships(membership_root: Path, audit_end: date) -> tuple[list[Membership], dict]:
    manifest = json.loads((membership_root / "manifest.json").read_text(encoding="utf-8"))
    observed_hash = str(manifest.get("dataset_hash") or "")
    if observed_hash != EXPECTED_MEMBERSHIP_DATASET_HASH:
        raise RuntimeError(
            f"unexpected S&P membership dataset hash: {observed_hash} "
            f"!= {EXPECTED_MEMBERSHIP_DATASET_HASH}"
        )
    rows = _read_csv(membership_root / "sp500-membership-intervals.csv.gz", gz=True)
    memberships: list[Membership] = []
    for row in rows:
        start_text = str(row["member_from"])
        end_text = str(row.get("member_until_exclusive") or "")
        memberships.append(
            Membership(
                ticker=str(row["ticker"]).upper(),
                start=_d(start_text),
                end=_d(end_text, audit_end),
                start_text=start_text,
                end_text=end_text,
                confidence=str(row.get("confidence") or ""),
            )
        )
    memberships.sort(key=lambda m: (m.ticker, m.start, m.end))
    return memberships, manifest


def _membership_for_gap(
    source: str,
    gap_from: date,
    gap_until: date,
    by_ticker: Mapping[str, list[Membership]],
) -> Membership | None:
    matches = [
        m
        for m in by_ticker.get(source, ())
        if m.start <= gap_from and gap_until <= m.end
    ]
    return matches[0] if len(matches) == 1 else None


def _clip_segment(
    *,
    membership: Membership,
    resolved_ticker: str,
    security_id: str,
    start: date,
    end: date,
    authority: str,
) -> Segment | None:
    left = max(membership.start, start)
    right = min(membership.end, end)
    if left >= right:
        return None
    return Segment(
        source_ticker=membership.ticker,
        member_from=membership.start_text,
        member_until_exclusive=membership.end_text,
        membership_confidence=membership.confidence,
        resolved_ticker=resolved_ticker.upper(),
        security_id=str(security_id),
        start=left,
        end=right,
        authority=authority,
    )


def _load_segments(
    *,
    memberships: Sequence[Membership],
    identity_root: Path,
    alias_root: Path,
    web_alias_root: Path,
    cik_alias_root: Path,
    audit_end: date,
) -> tuple[list[Segment], list[dict[str, str]], set[tuple[str, str, str]],
           list[tuple[str, date, date]], list[tuple[str, date, date]]]:
    by_key = {m.key: m for m in memberships}
    by_ticker: dict[str, list[Membership]] = defaultdict(list)
    for m in memberships:
        by_ticker[m.ticker].append(m)

    segments: list[Segment] = []
    conflicts: list[dict[str, str]] = []

    # Direct causal identity bindings.
    for row in _read_csv(identity_root / "sp500-security-bindings.csv.gz", gz=True):
        key = (
            str(row["ticker"]).upper(),
            str(row["member_from"]),
            str(row.get("member_until_exclusive") or ""),
        )
        membership = by_key.get(key)
        if membership is None:
            conflicts.append({
                "scope": "SEGMENT",
                "source_ticker": key[0],
                "from_date": str(row.get("binding_from") or ""),
                "until_exclusive": str(row.get("binding_until_exclusive") or ""),
                "reason": "DIRECT_BINDING_MEMBERSHIP_KEY_NOT_FOUND",
                "detail": repr(key),
            })
            continue
        seg = _clip_segment(
            membership=membership,
            resolved_ticker=str(row["ticker"]),
            security_id=str(row["security_id"]),
            start=_d(str(row["binding_from"])),
            end=_d(str(row.get("binding_until_exclusive") or ""), membership.end),
            authority="DIRECT_CAUSAL_SEP_IDENTITY",
        )
        if seg:
            segments.append(seg)

    # Unique vendor-discovery alias whose mapped ticker has actual SEP overlap.
    for row in _read_csv(alias_root / "resolved-aliases.csv.gz", gz=True):
        key = (
            str(row["sp500_ticker"]).upper(),
            str(row["member_from"]),
            str(row.get("member_until_exclusive") or ""),
        )
        membership = by_key.get(key)
        if membership is None:
            conflicts.append({
                "scope": "SEGMENT",
                "source_ticker": key[0],
                "from_date": str(row.get("first_overlap_session") or ""),
                "until_exclusive": str(row.get("last_overlap_session") or ""),
                "reason": "ALIAS_MEMBERSHIP_KEY_NOT_FOUND",
                "detail": repr(key),
            })
            continue
        seg = _clip_segment(
            membership=membership,
            resolved_ticker=str(row["resolved_ticker"]),
            security_id=str(row["security_id"]),
            start=_d(str(row["first_overlap_session"])),
            end=_inclusive_end_to_exclusive(str(row["last_overlap_session"])),
            authority="UNIQUE_TICKERS_DISCOVERY_PLUS_CAUSAL_SEP_OVERLAP",
        )
        if seg:
            segments.append(seg)

    # Bounded web-proven mappings.
    for row in _read_csv(web_alias_root / "accepted-web-aliases.csv"):
        source = str(row["source_ticker"]).upper()
        gap_from = _d(str(row["gap_from"]))
        gap_until = _d(str(row["gap_until_exclusive"]))
        membership = _membership_for_gap(source, gap_from, gap_until, by_ticker)
        if membership is None:
            conflicts.append({
                "scope": "SEGMENT",
                "source_ticker": source,
                "from_date": gap_from.isoformat(),
                "until_exclusive": gap_until.isoformat(),
                "reason": "WEB_ALIAS_MEMBERSHIP_NOT_UNIQUE",
                "detail": str(row.get("evidence_url") or ""),
            })
            continue
        seg = _clip_segment(
            membership=membership,
            resolved_ticker=str(row["resolved_ticker"]),
            security_id=str(row["security_id"]),
            start=_d(str(row["binding_from"])),
            end=_d(str(row["binding_until_exclusive"])),
            authority="WEB_PROVEN_BOUNDED_ALIAS_PLUS_CAUSAL_SEP_OVERLAP",
        )
        if seg:
            segments.append(seg)

    # Unique SEC-CIK issuer-link candidate with actual causal SEP overlap.
    for row in _read_csv(cik_alias_root / "unique-cik-aliases.csv"):
        source = str(row["ticker"]).upper()
        gap_from = _d(str(row["gap_from"]))
        gap_until = _d(str(row["gap_until_exclusive"]))
        membership = _membership_for_gap(source, gap_from, gap_until, by_ticker)
        if membership is None:
            conflicts.append({
                "scope": "SEGMENT",
                "source_ticker": source,
                "from_date": gap_from.isoformat(),
                "until_exclusive": gap_until.isoformat(),
                "reason": "CIK_ALIAS_MEMBERSHIP_NOT_UNIQUE",
                "detail": str(row.get("issuer_cik") or ""),
            })
            continue
        seg = _clip_segment(
            membership=membership,
            resolved_ticker=str(row["candidate_ticker"]),
            security_id=str(row["security_id"]),
            start=_d(str(row["first_overlap_session"])),
            end=_inclusive_end_to_exclusive(str(row["last_overlap_session"])),
            authority="UNIQUE_SEC_CIK_ISSUER_LINK_PLUS_CAUSAL_SEP_OVERLAP",
        )
        if seg:
            segments.append(seg)

    # Exact duplicate evidence is harmless; preserve the strongest deterministic
    # authority label only once.
    dedup: dict[tuple[str, str, str, str, str, date, date], Segment] = {}
    for seg in segments:
        key = (
            seg.source_ticker, seg.member_from, seg.member_until_exclusive,
            seg.resolved_ticker, seg.security_id, seg.start, seg.end,
        )
        prior = dedup.get(key)
        if prior is None or seg.authority < prior.authority:
            dedup[key] = seg
    segments = sorted(
        dedup.values(),
        key=lambda s: (
            s.source_ticker, s.start, s.end, s.resolved_ticker, s.security_id, s.authority
        ),
    )

    stage3_ambiguous_keys = {
        (
            str(r["sp500_ticker"]).upper(),
            str(r["member_from"]),
            str(r.get("member_until_exclusive") or ""),
        )
        for r in _read_csv(alias_root / "ambiguous-aliases.csv.gz", gz=True)
    }
    cik_ambiguous = [
        (
            str(r["ticker"]).upper(),
            _d(str(r["gap_from"])),
            _d(str(r["gap_until_exclusive"])),
        )
        for r in _read_csv(cik_alias_root / "ambiguous-cik-aliases.csv")
    ]
    cik_unresolved = [
        (
            str(r["ticker"]).upper(),
            _d(str(r["gap_from"])),
            _d(str(r["gap_until_exclusive"])),
        )
        for r in _read_csv(cik_alias_root / "unresolved-cik-aliases.csv")
    ]
    return segments, conflicts, stage3_ambiguous_keys, cik_ambiguous, cik_unresolved


def _range_contains(ranges: Sequence[tuple[str, date, date]], ticker: str, d: date) -> bool:
    return any(t == ticker and a <= d < b for t, a, b in ranges)


def _scan_sep_sessions(
    sharadar_root: Path, start: date, end_inclusive: date
) -> Iterable[tuple[date, set[str]]]:
    for year in range(start.year, end_inclusive.year + 1):
        path = sharadar_root / f"SHARADAR_SEP_{year}.csv.gz"
        if not path.exists():
            raise FileNotFoundError(path)
        by_date: dict[date, set[str]] = defaultdict(set)
        with gzip.open(path, "rt", encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            if not reader.fieldnames or "ticker" not in reader.fieldnames or "date" not in reader.fieldnames:
                raise RuntimeError(f"SEP file missing ticker/date columns: {path}")
            for row in reader:
                ds = str(row.get("date") or "")[:10]
                ticker = str(row.get("ticker") or "").strip().upper()
                if not ds or not ticker:
                    continue
                d = date.fromisoformat(ds)
                if start <= d <= end_inclusive:
                    by_date[d].add(ticker)
        for d in sorted(by_date):
            observed = by_date[d]
            if len(observed) >= MIN_TICKERS_PER_SESSION:
                yield d, observed


def build(
    *,
    membership_root: Path,
    identity_root: Path,
    alias_root: Path,
    trading_gap_root: Path,
    web_alias_root: Path,
    cik_alias_root: Path,
    sharadar_root: Path,
    output: Path,
    window_start: str = "1997-12-31",
    window_end: str = "2005-12-30",
) -> dict:
    start = date.fromisoformat(window_start)
    end = date.fromisoformat(window_end)
    if end < start:
        raise ValueError("window_end precedes window_start")
    audit_end = date(2026, 9, 4)

    memberships, membership_manifest = _load_memberships(membership_root, audit_end)
    segments, static_conflicts, stage3_ambiguous_keys, cik_ambiguous, cik_unresolved = _load_segments(
        memberships=memberships,
        identity_root=identity_root,
        alias_root=alias_root,
        web_alias_root=web_alias_root,
        cik_alias_root=cik_alias_root,
        audit_end=audit_end,
    )
    # Ensure we are materializing from the trading-session-filtered diagnostic
    # produced by the same closure pipeline, even though eligibility is ultimately
    # proven session-by-session against SEP below.
    trading_gap_summary = json.loads(
        (trading_gap_root / "trading-gap-summary.json").read_text(encoding="utf-8")
    )
    if trading_gap_summary.get("status") != "TRADING_GAP_FILTER_COMPLETE":
        raise RuntimeError("trading gap diagnostic is not complete")

    memberships_in_window = [
        m for m in memberships if m.start <= end and m.end > start
    ]
    memberships_by_key = {m.key: m for m in memberships_in_window}
    segments_by_key: dict[tuple[str, str, str], list[Segment]] = defaultdict(list)
    for seg in segments:
        if seg.membership_key in memberships_by_key and seg.start <= end and seg.end > start:
            segments_by_key[seg.membership_key].append(seg)

    eligibility_rows: list[dict[str, object]] = []
    exclusion_rows: list[dict[str, object]] = []
    conflicts = list(static_conflicts)
    daily_counts: list[int] = []
    session_count = 0
    source_membership_sessions = 0
    eligible_source_sessions = 0
    exclusion_reasons: Counter[str] = Counter()
    authority_counts: Counter[str] = Counter()

    for session, observed_tickers in _scan_sep_sessions(sharadar_root, start, end):
        session_count += 1
        selected: list[tuple[Membership, Segment]] = []
        excluded_today: list[dict[str, object]] = []

        for membership in memberships_in_window:
            if not (membership.start <= session < membership.end):
                continue
            source_membership_sessions += 1
            active = [
                seg for seg in segments_by_key.get(membership.key, ())
                if seg.start <= session < seg.end and seg.resolved_ticker in observed_tickers
            ]
            identities = {
                (seg.resolved_ticker, seg.security_id) for seg in active
            }
            if len(identities) == 1:
                # Multiple evidence paths that agree on identity are fine.
                resolved_ticker, security_id = next(iter(identities))
                agreeing = [
                    seg for seg in active
                    if seg.resolved_ticker == resolved_ticker and seg.security_id == security_id
                ]
                chosen = sorted(agreeing, key=lambda s: s.authority)[0]
                selected.append((membership, chosen))
                continue

            if len(identities) > 1:
                reason = "CONFLICTING_APPROVED_IDENTITY_MAPPINGS_EXCLUDED"
                detail = ";".join(
                    f"{t}:{sid}" for t, sid in sorted(identities)
                )
                conflicts.append({
                    "scope": "SESSION",
                    "source_ticker": membership.ticker,
                    "from_date": session.isoformat(),
                    "until_exclusive": (session + timedelta(days=1)).isoformat(),
                    "reason": reason,
                    "detail": detail,
                })
            elif membership.key in stage3_ambiguous_keys:
                reason = "STAGE3_AMBIGUOUS_IDENTITY"
                detail = "multiple causal SEP alias candidates"
            elif _range_contains(cik_ambiguous, membership.ticker, session):
                reason = "SEC_CIK_AMBIGUOUS_IDENTITY"
                detail = "multiple SEC-CIK-linked SEP alias candidates"
            elif _range_contains(cik_unresolved, membership.ticker, session):
                reason = "NO_APPROVED_CAUSAL_IDENTITY_MAPPING"
                detail = "SEC CIK did not yield a unique SEP alias"
            else:
                reason = "NO_APPROVED_CAUSAL_IDENTITY_MAPPING"
                detail = "no approved mapped ticker observed on this market session"

            excluded_today.append({
                "date": session.isoformat(),
                "source_ticker": membership.ticker,
                "member_from": membership.start_text,
                "member_until_exclusive": membership.end_text,
                "membership_confidence": membership.confidence,
                "reason": reason,
                "detail": detail,
            })

        # A single resolved ticker cannot represent two simultaneous S&P source
        # constituents. Exclude both sides if this ever occurs.
        reverse: dict[str, list[tuple[Membership, Segment]]] = defaultdict(list)
        for item in selected:
            reverse[item[1].resolved_ticker].append(item)
        duplicate_sources = {
            m.ticker
            for items in reverse.values() if len(items) > 1
            for m, _seg in items
        }
        if duplicate_sources:
            kept: list[tuple[Membership, Segment]] = []
            for membership, seg in selected:
                if membership.ticker not in duplicate_sources:
                    kept.append((membership, seg))
                    continue
                reason = "DUPLICATE_RESOLVED_TICKER_ON_SESSION"
                detail = f"resolved ticker {seg.resolved_ticker} maps from multiple constituents"
                excluded_today.append({
                    "date": session.isoformat(),
                    "source_ticker": membership.ticker,
                    "member_from": membership.start_text,
                    "member_until_exclusive": membership.end_text,
                    "membership_confidence": membership.confidence,
                    "reason": reason,
                    "detail": detail,
                })
                conflicts.append({
                    "scope": "SESSION",
                    "source_ticker": membership.ticker,
                    "from_date": session.isoformat(),
                    "until_exclusive": (session + timedelta(days=1)).isoformat(),
                    "reason": reason,
                    "detail": detail,
                })
            selected = kept

        selected.sort(key=lambda x: (x[1].resolved_ticker, x[0].ticker))
        for membership, seg in selected:
            eligibility_rows.append({
                "date": session.isoformat(),
                "source_ticker": membership.ticker,
                "resolved_ticker": seg.resolved_ticker,
                "security_id": seg.security_id,
                "membership_confidence": membership.confidence,
                "authority": seg.authority,
            })
            authority_counts[seg.authority] += 1
        eligible_source_sessions += len(selected)
        daily_counts.append(len(selected))

        for row in sorted(excluded_today, key=lambda r: str(r["source_ticker"])):
            exclusion_rows.append(row)
            exclusion_reasons[str(row["reason"])] += 1

    if not session_count:
        raise RuntimeError("no market sessions in requested window")
    if not eligibility_rows:
        raise RuntimeError("best-effort universe produced no eligible rows")

    output.mkdir(parents=True, exist_ok=True)
    segment_path = output / "sp500-best-effort-segments.csv.gz"
    eligibility_path = output / "sp500-best-effort-eligibility.csv.gz"
    exclusion_path = output / "sp500-best-effort-excluded-sessions.csv.gz"
    conflict_path = output / "sp500-best-effort-conflicts.csv"

    segment_rows = [
        {
            "source_ticker": s.source_ticker,
            "member_from": s.member_from,
            "member_until_exclusive": s.member_until_exclusive,
            "membership_confidence": s.membership_confidence,
            "resolved_ticker": s.resolved_ticker,
            "security_id": s.security_id,
            "segment_from": s.start.isoformat(),
            "segment_until_exclusive": s.end.isoformat(),
            "authority": s.authority,
        }
        for s in segments
        if s.start <= end and s.end > start
    ]
    _write_gzip_csv(segment_path, SEGMENT_FIELDS, segment_rows)
    _write_gzip_csv(eligibility_path, ELIGIBILITY_FIELDS, eligibility_rows)
    _write_gzip_csv(exclusion_path, EXCLUSION_FIELDS, exclusion_rows)
    _write_csv(
        conflict_path,
        CONFLICT_FIELDS,
        sorted(
            conflicts,
            key=lambda r: (
                str(r.get("source_ticker", "")),
                str(r.get("from_date", "")),
                str(r.get("reason", "")),
            ),
        ),
    )

    daily_sorted = sorted(daily_counts)
    summary = {
        "schema": SCHEMA,
        "status": STATUS,
        "formal_pit_certified": False,
        "best_effort_pit": True,
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
        "membership_dataset_hash": membership_manifest["dataset_hash"],
        "membership_source_status": membership_manifest.get("status"),
        "early_membership_caveat": (
            "S&P membership before 2001-01-16 comes from the pinned secondary historical "
            "source's incomplete early-history region and is explicitly best-effort."
        ),
        "identity_policy": (
            "dated S&P membership plus approved causal SEP identity overlap; mapped ticker "
            "must be observed on the exact market session; ambiguity/conflict is excluded"
        ),
        "sec_cik_policy": (
            "SEC CIK is issuer-link discovery only; admitted CIK aliases additionally require "
            "a unique causal SEP security overlap"
        ),
        "market_session_policy": (
            f"frozen SEP date with at least {MIN_TICKERS_PER_SESSION} distinct observed tickers"
        ),
        "market_sessions": session_count,
        "source_membership_sessions": source_membership_sessions,
        "eligible_source_sessions": eligible_source_sessions,
        "excluded_source_sessions": len(exclusion_rows),
        "exclusion_fraction_of_source_membership_sessions": (
            len(exclusion_rows) / source_membership_sessions
            if source_membership_sessions else None
        ),
        "daily_constituents": {
            "min": min(daily_sorted),
            "median": float(median(daily_sorted)),
            "max": max(daily_sorted),
            "first_session": daily_counts[0],
            "last_session": daily_counts[-1],
        },
        "eligible_rows": len(eligibility_rows),
        "approved_segments_in_window": len(segment_rows),
        "conflict_rows": len(conflicts),
        "exclusion_reason_counts": dict(sorted(exclusion_reasons.items())),
        "authority_session_counts": dict(sorted(authority_counts.items())),
        "stage3_reference": {
            "true_trading_gap_intervals": trading_gap_summary.get("output_gap_intervals"),
            "market_session_start": trading_gap_summary.get("market_session_start"),
            "market_session_end": trading_gap_summary.get("market_session_end"),
        },
    }
    summary_path = output / "best-effort-summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    members = [segment_path, eligibility_path, exclusion_path, conflict_path, summary_path]
    checksums = output / "SHA256SUMS.txt"
    checksums.write_text(
        "".join(f"{_sha256(p)}  {p.name}\n" for p in sorted(members)),
        encoding="utf-8",
    )
    return summary


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--membership-root", type=Path, required=True)
    p.add_argument("--identity-root", type=Path, required=True)
    p.add_argument("--alias-root", type=Path, required=True)
    p.add_argument("--trading-gap-root", type=Path, required=True)
    p.add_argument("--web-alias-root", type=Path, required=True)
    p.add_argument("--cik-alias-root", type=Path, required=True)
    p.add_argument("--sharadar-root", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--window-start", default="1997-12-31")
    p.add_argument("--window-end", default="2005-12-30")
    args = p.parse_args()
    summary = build(**vars(args))
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
