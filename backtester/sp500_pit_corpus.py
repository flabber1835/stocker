#!/usr/bin/env python3
"""Build a deterministic best-effort point-in-time S&P 500 universe corpus."""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterable

SCHEMA = "backtester.sp500-pit-corpus/1"
SOURCE_REPO = "fja05680/sp500"
SOURCE_COMMIT = "c31ac3cc56f28cf9a02b4e694eff7ceab596a0ff"
SOURCE_FILE = "sp500_ticker_start_end.csv"
SOURCE_GIT_BLOB_SHA1 = "4aeb5f6046dea43063f9c7be72dfdf16e96d2821"
SOURCE_AS_OF = "2026-07-13"
DEFAULT_START = "1996-01-02"
DEFAULT_END = "2026-09-03"
PRIMARY_SECONDARY_START = "2001-01-16"
SEALED_OOS_END = "2005-12-30"

INTERVAL_COLUMNS = (
    "ticker", "member_from", "member_until_exclusive", "confidence",
    "start_authority", "end_authority",
)
TRANSITION_COLUMNS = (
    "effective_date", "action", "ticker", "confidence", "authority",
)


@dataclass
class Interval:
    ticker: str
    member_from: str
    member_until_exclusive: str | None
    confidence: str
    start_authority: str
    end_authority: str = ""


def _iso(value: str) -> str:
    return date.fromisoformat(value).isoformat()


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def git_blob_sha1(path: Path) -> str:
    data = path.read_bytes()
    return hashlib.sha1(b"blob " + str(len(data)).encode("ascii") + b"\0" + data).hexdigest()


def _base_confidence(original_start: str) -> str:
    if original_start < PRIMARY_SECONDARY_START:
        return "secondary_early_best_effort"
    return "secondary_historical"


def load_base_intervals(source: Path, start: str, end: str) -> list[Interval]:
    start = _iso(start)
    end = _iso(end)
    rows: list[Interval] = []
    with source.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        required = {"ticker", "start_date", "end_date"}
        fields = set(reader.fieldnames or ())
        if not required.issubset(fields):
            raise RuntimeError(f"source columns missing: {sorted(required - fields)}")
        for raw in reader:
            ticker = str(raw["ticker"]).strip()
            original_start = _iso(str(raw["start_date"]).strip())
            raw_end = str(raw["end_date"] or "").strip()
            original_end = _iso(raw_end) if raw_end else None
            if not ticker:
                raise RuntimeError("blank source ticker")
            # end_date is the first snapshot where the ticker is absent.
            if original_end is not None and original_end <= start:
                continue
            if original_start > end:
                continue
            member_from = max(original_start, start)
            member_until = original_end if original_end is not None and original_end <= end else None
            if member_until is not None and member_until <= member_from:
                raise RuntimeError(
                    f"non-positive membership interval: {ticker} {member_from}..{member_until}"
                )
            rows.append(Interval(
                ticker=ticker,
                member_from=member_from,
                member_until_exclusive=member_until,
                confidence=_base_confidence(original_start),
                start_authority=(
                    f"secondary:{SOURCE_REPO}@{SOURCE_COMMIT}:{SOURCE_FILE}"
                ),
                end_authority=(
                    f"secondary:{SOURCE_REPO}@{SOURCE_COMMIT}:{SOURCE_FILE}"
                    if member_until is not None else ""
                ),
            ))
    _validate_intervals(rows)
    return rows


def _active(interval: Interval, session: str) -> bool:
    return (
        interval.member_from <= session
        and (interval.member_until_exclusive is None or session < interval.member_until_exclusive)
    )


def membership_on(intervals: Iterable[Interval], session: str) -> tuple[str, ...]:
    session = _iso(session)
    members = sorted(i.ticker for i in intervals if _active(i, session))
    if len(members) != len(set(members)):
        raise RuntimeError(f"duplicate active S&P 500 ticker on {session}")
    return tuple(members)


def load_overlay(path: Path, *, start: str, end: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    with path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        required = {"effective_date", "action", "ticker", "announced_date", "authority_url", "authority"}
        fields = set(reader.fieldnames or ())
        if not required.issubset(fields):
            raise RuntimeError(f"overlay columns missing: {sorted(required - fields)}")
        for raw in reader:
            effective = _iso(str(raw["effective_date"]).strip())
            announced = _iso(str(raw["announced_date"]).strip())
            action = str(raw["action"]).strip().lower()
            ticker = str(raw["ticker"]).strip()
            authority_url = str(raw["authority_url"]).strip()
            authority = str(raw["authority"]).strip()
            if action not in {"add", "delete"}:
                raise RuntimeError(f"invalid overlay action: {action}")
            if not ticker or not authority_url or not authority:
                raise RuntimeError("overlay row has blank required field")
            if announced >= effective:
                raise RuntimeError(f"overlay announcement is not strict-prior: {ticker} {announced} >= {effective}")
            if effective <= SOURCE_AS_OF:
                raise RuntimeError(f"overlay overlaps pinned historical source horizon: {effective}")
            if start <= effective <= end:
                rows.append({
                    "effective_date": effective,
                    "action": action,
                    "ticker": ticker,
                    "announced_date": announced,
                    "authority_url": authority_url,
                    "authority": authority,
                })
    action_order = {"delete": 0, "add": 1}
    rows.sort(key=lambda r: (r["effective_date"], action_order[r["action"]], r["ticker"]))
    per_date: dict[str, dict[str, int]] = defaultdict(lambda: {"add": 0, "delete": 0})
    for row in rows:
        per_date[row["effective_date"]][row["action"]] += 1
    for effective, counts in per_date.items():
        if counts["add"] != counts["delete"]:
            raise RuntimeError(f"unbalanced S&P 500 overlay on {effective}: {counts}")
    return rows


def apply_overlay(intervals: list[Interval], overlay: list[dict[str, str]]) -> list[Interval]:
    result = [Interval(**vars(item)) for item in intervals]
    for event in overlay:
        effective = event["effective_date"]
        ticker = event["ticker"]
        authority = f"official:{event['authority']}:{event['authority_url']}"
        active = [item for item in result if item.ticker == ticker and _active(item, effective)]
        if event["action"] == "delete":
            if len(active) != 1:
                raise RuntimeError(
                    f"official deletion requires exactly one active interval: {ticker} {effective} active={len(active)}"
                )
            active[0].member_until_exclusive = effective
            active[0].end_authority = authority
        else:
            if active:
                raise RuntimeError(f"official addition already active: {ticker} {effective}")
            result.append(Interval(
                ticker=ticker,
                member_from=effective,
                member_until_exclusive=None,
                confidence="official_primary",
                start_authority=authority,
            ))
        _validate_intervals(result)
    return sorted(result, key=lambda i: (i.ticker, i.member_from, i.member_until_exclusive or "9999-12-31"))


def _validate_intervals(intervals: list[Interval]) -> None:
    by_ticker: dict[str, list[Interval]] = defaultdict(list)
    seen: set[tuple[str, str, str | None]] = set()
    for item in intervals:
        key = (item.ticker, item.member_from, item.member_until_exclusive)
        if key in seen:
            raise RuntimeError(f"duplicate membership interval: {key}")
        seen.add(key)
        by_ticker[item.ticker].append(item)
    for ticker, items in by_ticker.items():
        items.sort(key=lambda i: i.member_from)
        previous: Interval | None = None
        for item in items:
            if item.member_until_exclusive is not None and item.member_until_exclusive <= item.member_from:
                raise RuntimeError(f"non-positive membership interval for {ticker}")
            if previous is not None:
                if previous.member_until_exclusive is None:
                    raise RuntimeError(f"open interval followed by another interval for {ticker}")
                if item.member_from < previous.member_until_exclusive:
                    raise RuntimeError(f"overlapping intervals for {ticker}: {previous} / {item}")
            previous = item


def _write_gzip_csv(path: Path, columns: tuple[str, ...], rows: list[dict[str, str]]) -> None:
    raw = path.open("wb")
    gz = gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0, compresslevel=6)
    text = io.TextIOWrapper(gz, encoding="utf-8", newline="")
    writer = csv.DictWriter(text, fieldnames=columns, lineterminator="\n", extrasaction="raise")
    writer.writeheader()
    writer.writerows(rows)
    text.flush()
    text.detach()
    gz.close()
    raw.close()


def _transition_rows(intervals: list[Interval]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for item in intervals:
        rows.append({
            "effective_date": item.member_from,
            "action": "add",
            "ticker": item.ticker,
            "confidence": item.confidence,
            "authority": item.start_authority,
        })
        if item.member_until_exclusive is not None:
            rows.append({
                "effective_date": item.member_until_exclusive,
                "action": "delete",
                "ticker": item.ticker,
                "confidence": item.confidence,
                "authority": item.end_authority,
            })
    action_order = {"delete": 0, "add": 1}
    return sorted(rows, key=lambda r: (r["effective_date"], action_order[r["action"]], r["ticker"]))


def _member_record(path: Path) -> dict[str, object]:
    return {"sha256": _sha256(path), "bytes": path.stat().st_size}


def build(source: Path, overlay_path: Path, output: Path, *, start: str = DEFAULT_START, end: str = DEFAULT_END) -> dict:
    start = _iso(start)
    end = _iso(end)
    if end < start:
        raise RuntimeError("S&P 500 corpus end precedes start")
    observed_blob = git_blob_sha1(source)
    if observed_blob != SOURCE_GIT_BLOB_SHA1:
        raise RuntimeError(f"pinned S&P source blob mismatch: {observed_blob} != {SOURCE_GIT_BLOB_SHA1}")

    base = load_base_intervals(source, start, end)
    overlay = load_overlay(overlay_path, start=start, end=end)
    intervals = apply_overlay(base, overlay)
    _validate_intervals(intervals)

    output.mkdir(parents=True, exist_ok=True)
    interval_path = output / "sp500-membership-intervals.csv.gz"
    transition_path = output / "sp500-transitions.csv.gz"
    interval_rows = [{
        "ticker": item.ticker,
        "member_from": item.member_from,
        "member_until_exclusive": item.member_until_exclusive or "",
        "confidence": item.confidence,
        "start_authority": item.start_authority,
        "end_authority": item.end_authority,
    } for item in intervals]
    _write_gzip_csv(interval_path, INTERVAL_COLUMNS, interval_rows)
    transitions = _transition_rows(intervals)
    _write_gzip_csv(transition_path, TRANSITION_COLUMNS, transitions)

    checkpoint_dates = [
        "1996-01-02", "2001-01-16", "2006-01-03", SOURCE_AS_OF,
        "2026-08-05", "2026-08-18", end,
    ]
    checkpoints: dict[str, dict[str, object]] = {}
    for checkpoint in checkpoint_dates:
        if start <= checkpoint <= end:
            members = membership_on(intervals, checkpoint)
            checkpoints[checkpoint] = {
                "count": len(members),
                "members_sha256": hashlib.sha256(("\n".join(members) + "\n").encode("utf-8")).hexdigest(),
            }

    transition_dates = sorted({start, end, *(i.member_from for i in intervals), *(i.member_until_exclusive for i in intervals if i.member_until_exclusive)})
    min_count = 10**9
    max_count = 0
    min_date = ""
    max_date = ""
    for session in transition_dates:
        if not (start <= session <= end):
            continue
        count = len(membership_on(intervals, session))
        if count < min_count:
            min_count, min_date = count, session
        if count > max_count:
            max_count, max_date = count, session
    if min_count < 480 or max_count > 510:
        raise RuntimeError(f"implausible S&P 500 constituent count range: {min_count}..{max_count}")

    quality = {
        "schema": "backtester.sp500-pit-quality/1",
        "segments": [
            {
                "start": start,
                "end": "2001-01-15" if start <= "2001-01-15" else start,
                "confidence": "secondary_early_best_effort",
                "reason": "Pinned historical source maintainer reports possible missing names in earliest snapshots.",
            },
            {
                "start": max(start, PRIMARY_SECONDARY_START),
                "end": SOURCE_AS_OF,
                "confidence": "secondary_historical",
                "reason": "Pinned historical point-in-time constituent series.",
            },
            {
                "start": "2026-07-14",
                "end": end,
                "confidence": "secondary_continuity_plus_official_changes",
                "reason": "Pinned July-13 state carried forward with subsequent S&P 500 changes from official S&P DJI announcements.",
            },
        ],
        "sealed_ldrc_oos": {"start": "1996-01-02", "end": SEALED_OOS_END},
        "transition_count_range": {
            "min": min_count, "min_date": min_date, "max": max_count, "max_date": max_date,
        },
    }
    quality_path = output / "quality.json"
    quality_path.write_text(json.dumps(quality, sort_keys=True, indent=2) + "\n", encoding="utf-8")

    members = {
        interval_path.name: _member_record(interval_path),
        transition_path.name: _member_record(transition_path),
        quality_path.name: _member_record(quality_path),
    }
    aggregate = hashlib.sha256()
    for name in sorted(members):
        record = members[name]
        aggregate.update(f"{name}\0{record['sha256']}\0{record['bytes']}\n".encode("utf-8"))

    manifest = {
        "schema": SCHEMA,
        "status": "BEST_EFFORT_PIT",
        "start": start,
        "end": end,
        "sealed_ldrc_oos_end": SEALED_OOS_END,
        "source": {
            "repo": SOURCE_REPO,
            "commit": SOURCE_COMMIT,
            "file": SOURCE_FILE,
            "git_blob_sha1": observed_blob,
            "sha256": _sha256(source),
            "as_of": SOURCE_AS_OF,
        },
        "overlay": {
            "file": str(overlay_path),
            "sha256": _sha256(overlay_path),
            "events": len(overlay),
            "official_events": sum(1 for row in overlay if row["authority"] == "S&P Dow Jones Indices"),
        },
        "interval_rows": len(intervals),
        "unique_tickers": len({i.ticker for i in intervals}),
        "confidence_counts": dict(sorted((key, sum(1 for i in intervals if i.confidence == key)) for key in {i.confidence for i in intervals})),
        "checkpoints": checkpoints,
        "members": members,
        "dataset_hash": aggregate.hexdigest(),
    }
    manifest_path = output / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8")

    sum_members = [interval_path, transition_path, quality_path, manifest_path]
    (output / "SHA256SUMS.txt").write_text(
        "".join(f"{_sha256(path)}  {path.name}\n" for path in sum_members),
        encoding="utf-8",
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--overlay", default=Path("backtester/data/sp500_official_overlay_2026.csv"), type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--start", default=DEFAULT_START)
    parser.add_argument("--end", default=DEFAULT_END)
    args = parser.parse_args()
    manifest = build(args.source, args.overlay, args.output, start=args.start, end=args.end)
    print(json.dumps(manifest, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
