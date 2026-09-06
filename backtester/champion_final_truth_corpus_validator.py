#!/usr/bin/env python3
"""Validate the complete manual-review security-truth corpus before replay.

This validator is independent of the executable classifier loader so schema
problems are enumerated across the whole corpus in one pass. It is stdlib-only
and deliberately does not touch the canonical PIT package or run performance.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date
import json
from pathlib import Path
import re
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MANUAL = ROOT / "research/champion-economic-integrity/security-truth/manual-review"

PARENT_FILES = (
    "durable-shard-00.json", "durable-shard-01.json", "durable-shard-02.json",
    "durable-shard-03.json", "durable-shard-04.json", "durable-shard-05.json",
    "durable-shard-06.json", "durable-shard-07.json", "durable-shard-08.json",
    "durable-shard-09.json",
    "leadership-shard-00.json", "leadership-shard-01.json",
    "leadership-shard-02.json", "leadership-shard-03.json",
    "ranking-shard-00.json", "ranking-shard-01.json",
)
CLEANUP_FILES = (
    "durable-shard-06-cleanup.json", "durable-shard-07-cleanup.json",
    "durable-shard-09-cleanup.json", "leadership-shard-00-cleanup.json",
    "leadership-shard-01-cleanup.json", "ranking-shard-01-cleanup.json",
)
P0_FILE = "p0-fresh-path-delta.json"
EXPECTED_PARENT_COUNTS = {"durable": 442, "leadership": 182, "ranking": 61}
ALLOWED_DECISIONS = {"common", "non_common", "split", "unresolved"}
CANONICAL_KEYS = ("canonical_interval", "interval", "decision_interval", "review_interval")
ROW_KEYS = ("cases", "reviews", "results")
INTERVAL_RE = re.compile(
    r"^\s*(\d{4}-\d{2}-\d{2})/(\d{4}-\d{2}-\d{2})(?::|\s+)(common|non_common)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Interval:
    first: str
    last: str
    classification: str


def _issue(issues: list[dict[str, Any]], code: str, source: str,
           case: dict[str, Any] | None, detail: str) -> None:
    issues.append({
        "code": code,
        "source": source,
        "security_id": None if case is None else str(case.get("security_id", "")) or None,
        "ticker": None if case is None else str(case.get("ticker", "")) or None,
        "detail": detail,
    })


def _decision(case: dict[str, Any]) -> str:
    return str(case.get("final_decision") or case.get("decision") or case.get("classification") or "").lower()


def _rows(doc: dict[str, Any], source: str, issues: list[dict[str, Any]]) -> list[Any]:
    found = [(key, doc.get(key)) for key in ROW_KEYS if key in doc]
    usable = [(key, value) for key, value in found if isinstance(value, list)]
    if len(usable) == 1:
        return usable[0][1]
    if len(usable) > 1:
        _issue(issues, "AMBIGUOUS_CASE_COLLECTION", source, None,
               f"multiple list collections: {[key for key, _ in usable]}")
        return []
    _issue(issues, "CASES_NOT_LIST", source, None,
           f"observed keys={[(key, type(value).__name__) for key, value in found]}")
    return []


def _canonical(case: dict[str, Any]) -> tuple[str, str] | None:
    value: Any = None
    for key in CANONICAL_KEYS:
        if case.get(key) is not None:
            value = case[key]
            break
    if value is None:
        return None
    if isinstance(value, str):
        normalized = value.replace(" — ", "/").replace("..", "/")
        if "/" not in normalized:
            return None
        a, b = normalized.split("/", 1)
        return a.strip(), b.strip()
    if isinstance(value, (list, tuple)) and len(value) == 2:
        return str(value[0]), str(value[1])
    if isinstance(value, dict):
        a = (value.get("first_session") or value.get("effective_first_session")
             or value.get("start") or value.get("first"))
        b = (value.get("last_session") or value.get("effective_last_session")
             or value.get("end") or value.get("last"))
        if a is not None and b is not None:
            return str(a), str(b)
    return None


def _valid_date(value: str) -> bool:
    try:
        date.fromisoformat(value)
        return True
    except (ValueError, TypeError):
        return False


def _parse_one_effective(row: Any, case_decision: str) -> Interval | None:
    if isinstance(row, dict):
        cls = str(row.get("classification") or row.get("decision") or "").lower()
        a = (row.get("first_session") or row.get("effective_first_session")
             or row.get("start") or row.get("first"))
        b = (row.get("last_session") or row.get("effective_last_session")
             or row.get("end") or row.get("last"))
        if cls in {"common", "non_common"} and a is not None and b is not None:
            return Interval(str(a), str(b), cls)
        return None
    if isinstance(row, (list, tuple)):
        if len(row) >= 3:
            cls = str(row[2]).lower()
            if cls in {"common", "non_common"}:
                return Interval(str(row[0]), str(row[1]), cls)
        if len(row) == 2 and case_decision in {"common", "non_common"}:
            return Interval(str(row[0]), str(row[1]), case_decision)
        return None
    if isinstance(row, str):
        normalized = row.replace(" — ", "/").replace("..", "/")
        match = INTERVAL_RE.match(normalized)
        if match:
            return Interval(match.group(1), match.group(2), match.group(3).lower())
    return None


def _parse_effective(case: dict[str, Any], source: str, issues: list[dict[str, Any]],
                     canonical: tuple[str, str] | None) -> list[Interval]:
    decision = _decision(case)
    raw_rows = case.get("effective_intervals")
    if raw_rows is None:
        rows: list[Any] = []
    elif isinstance(raw_rows, list):
        rows = raw_rows
    else:
        _issue(issues, "EFFECTIVE_INTERVALS_NOT_LIST", source, case, type(raw_rows).__name__)
        rows = []

    result: list[Interval] = []
    for index, row in enumerate(rows):
        parsed = _parse_one_effective(row, decision)
        if parsed is None:
            _issue(issues, "UNPARSEABLE_EFFECTIVE_INTERVAL", source, case,
                   f"effective_intervals[{index}]={row!r}")
        else:
            result.append(parsed)

    if not result and decision in {"common", "non_common"} and canonical is not None:
        result = [Interval(canonical[0], canonical[1], decision)]
    if not result and decision in {"common", "non_common", "split"}:
        _issue(issues, "RESOLVED_CASE_NOT_EXECUTABLE", source, case,
               f"decision={decision}; no parseable effective intervals and no usable canonical interval")
        return []
    if decision == "unresolved" and result:
        _issue(issues, "UNRESOLVED_CASE_HAS_EXECUTABLE_INTERVALS", source, case, repr(result))

    for row in result:
        if not _valid_date(row.first) or not _valid_date(row.last):
            _issue(issues, "INVALID_INTERVAL_DATE", source, case, repr(row))
            continue
        if row.first > row.last:
            _issue(issues, "REVERSED_INTERVAL", source, case, repr(row))
        if canonical is not None and (row.first < canonical[0] or row.last > canonical[1]):
            _issue(issues, "INTERVAL_OUTSIDE_CANONICAL", source, case,
                   f"interval={row.first}/{row.last}; canonical={canonical[0]}/{canonical[1]}")

    ordered = sorted(result, key=lambda x: x.first)
    for left, right in zip(ordered, ordered[1:]):
        if right.first <= left.last:
            _issue(issues, "OVERLAPPING_INTERVALS", source, case, f"{left!r} vs {right!r}")
    if decision in {"common", "non_common"} and any(row.classification != decision for row in result):
        _issue(issues, "DECISION_INTERVAL_CLASS_MISMATCH", source, case,
               f"decision={decision}; intervals={[row.classification for row in result]}")
    if decision == "split":
        classes = {row.classification for row in result}
        if len(result) < 2 or classes != {"common", "non_common"}:
            _issue(issues, "INVALID_SPLIT", source, case,
                   f"split requires >=2 intervals spanning common and non_common; got {result!r}")
    return ordered


def _load_json(path: Path, issues: list[dict[str, Any]]) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        _issue(issues, "JSON_LOAD_FAILURE", path.name, None, repr(exc))
        return {}
    if not isinstance(value, dict):
        _issue(issues, "JSON_ROOT_NOT_OBJECT", path.name, None, type(value).__name__)
        return {}
    return value


def validate_corpus(manual: Path = MANUAL) -> tuple[dict[str, Any], dict[str, list[Interval]]]:
    issues: list[dict[str, Any]] = []
    ledger: dict[str, list[Interval]] = {}
    unresolved: set[str] = set()
    parent_canonical: dict[str, tuple[str, str]] = {}
    parent_ticker_sids: dict[str, set[str]] = {}
    parent_seen: dict[str, str] = {}
    family_counts = {"durable": 0, "leadership": 0, "ranking": 0}

    for filename in PARENT_FILES:
        path = manual / filename
        if not path.exists():
            _issue(issues, "MISSING_SOURCE_FILE", filename, None, str(path))
            continue
        doc = _load_json(path, issues)
        cases = _rows(doc, filename, issues)
        family = filename.split("-shard-", 1)[0]
        family_counts[family] = family_counts.get(family, 0) + len(cases)
        for raw in cases:
            if not isinstance(raw, dict):
                _issue(issues, "CASE_NOT_OBJECT", filename, None, repr(raw))
                continue
            case = dict(raw)
            sid = str(case.get("security_id", ""))
            ticker = str(case.get("ticker", ""))
            if not sid:
                _issue(issues, "PARENT_CASE_MISSING_SECURITY_ID", filename, case, "")
                continue
            if sid in parent_seen:
                _issue(issues, "DUPLICATE_PARENT_SECURITY_ID", filename, case,
                       f"already present in {parent_seen[sid]}")
            else:
                parent_seen[sid] = filename
            if ticker:
                parent_ticker_sids.setdefault(ticker, set()).add(sid)
            decision = _decision(case)
            if decision not in ALLOWED_DECISIONS:
                _issue(issues, "INVALID_DECISION", filename, case, repr(decision))
                continue
            canonical = _canonical(case)
            if canonical is not None:
                if (not _valid_date(canonical[0]) or not _valid_date(canonical[1])
                        or canonical[0] > canonical[1]):
                    _issue(issues, "INVALID_CANONICAL_INTERVAL", filename, case, repr(canonical))
                previous = parent_canonical.get(sid)
                if previous is not None and previous != canonical:
                    _issue(issues, "CONFLICTING_PARENT_CANONICAL", filename, case,
                           f"{previous!r} vs {canonical!r}")
                parent_canonical[sid] = canonical
            intervals = _parse_effective(case, filename, issues, canonical)
            if decision == "unresolved":
                unresolved.add(sid)
                ledger.pop(sid, None)
            elif intervals:
                ledger[sid] = intervals

    for family, expected in EXPECTED_PARENT_COUNTS.items():
        actual = family_counts.get(family, 0)
        if actual != expected:
            _issue(issues, "PARENT_FAMILY_COUNT_MISMATCH", family, None,
                   f"expected={expected}; actual={actual}")
    expected_parent_total = sum(EXPECTED_PARENT_COUNTS.values())
    if len(parent_seen) != expected_parent_total:
        _issue(issues, "PARENT_UNIQUE_SECURITY_COUNT_MISMATCH", "parents", None,
               f"expected={expected_parent_total}; actual={len(parent_seen)}")

    cleanup_targets: set[str] = set()
    for filename in CLEANUP_FILES:
        path = manual / filename
        if not path.exists():
            _issue(issues, "MISSING_SOURCE_FILE", filename, None, str(path))
            continue
        doc = _load_json(path, issues)
        cases = _rows(doc, filename, issues)
        for raw in cases:
            if not isinstance(raw, dict):
                _issue(issues, "CASE_NOT_OBJECT", filename, None, repr(raw))
                continue
            case = dict(raw)
            ticker = str(case.get("ticker", ""))
            sid = str(case.get("security_id", ""))
            if not sid:
                matches = sorted(parent_ticker_sids.get(ticker, set()))
                if len(matches) != 1:
                    _issue(issues, "CLEANUP_TICKER_BINDING_NOT_UNIQUE", filename, case,
                           f"ticker={ticker!r}; parent_security_ids={matches}")
                    continue
                sid = matches[0]
                case["security_id"] = sid
            if sid not in parent_seen:
                _issue(issues, "CLEANUP_TARGET_NOT_IN_PARENT", filename, case, sid)
            if sid in cleanup_targets:
                _issue(issues, "DUPLICATE_CLEANUP_TARGET", filename, case, sid)
            cleanup_targets.add(sid)
            decision = _decision(case)
            if decision not in ALLOWED_DECISIONS:
                _issue(issues, "INVALID_DECISION", filename, case, repr(decision))
                continue
            canonical = _canonical(case) or parent_canonical.get(sid)
            intervals = _parse_effective(case, filename, issues, canonical)
            if decision == "unresolved":
                unresolved.add(sid)
                ledger.pop(sid, None)
            elif intervals:
                ledger[sid] = intervals
                unresolved.discard(sid)

    p0_path = manual / P0_FILE
    p0_new_count = 0
    if not p0_path.exists():
        _issue(issues, "MISSING_SOURCE_FILE", P0_FILE, None, str(p0_path))
    else:
        p0 = _load_json(p0_path, issues)
        new_cases = p0.get("new_adjudications")
        if not isinstance(new_cases, list):
            _issue(issues, "P0_NEW_ADJUDICATIONS_NOT_LIST", P0_FILE, None,
                   type(new_cases).__name__)
        else:
            p0_new_count = len(new_cases)
            for raw in new_cases:
                if not isinstance(raw, dict):
                    _issue(issues, "CASE_NOT_OBJECT", P0_FILE, None, repr(raw))
                    continue
                case = dict(raw)
                sid = str(case.get("security_id", ""))
                cls = str(case.get("classification") or case.get("decision") or "").lower()
                canonical = _canonical(case)
                if not sid:
                    _issue(issues, "P0_CASE_MISSING_SECURITY_ID", P0_FILE, case, "")
                    continue
                if sid in parent_seen:
                    _issue(issues, "P0_DUPLICATES_PARENT_SECURITY", P0_FILE, case, sid)
                if cls not in {"common", "non_common"}:
                    _issue(issues, "P0_INVALID_CLASSIFICATION", P0_FILE, case, repr(cls))
                    continue
                if canonical is None:
                    _issue(issues, "P0_MISSING_CANONICAL", P0_FILE, case, "")
                    continue
                ledger[sid] = [Interval(canonical[0], canonical[1], cls)]
            if p0.get("fresh_unresolved_type_count") not in (0, "0"):
                _issue(issues, "P0_DECLARED_UNRESOLVED_NONZERO", P0_FILE, None,
                       repr(p0.get("fresh_unresolved_type_count")))

    pds = "594891209465982980"
    if pds not in ledger:
        _issue(issues, "PDS_MISSING_FROM_FINAL_LEDGER", "integration",
               {"security_id": pds, "ticker": "PDS"}, "")
    else:
        ledger[pds] = [
            Interval("2006-07-05", "2010-06-01", "non_common"),
            Interval("2010-06-02", "2015-06-04", "common"),
        ]

    for sid, intervals in ledger.items():
        ordered = sorted(intervals, key=lambda x: x.first)
        for left, right in zip(ordered, ordered[1:]):
            if right.first <= left.last:
                _issue(issues, "FINAL_LEDGER_OVERLAP", "final-ledger",
                       {"security_id": sid}, f"{left!r} vs {right!r}")
        ledger[sid] = ordered

    if unresolved:
        for sid in sorted(unresolved, key=int):
            _issue(issues, "FINAL_UNRESOLVED_SECURITY", "final-ledger",
                   {"security_id": sid}, parent_seen.get(sid, "unknown parent"))

    expected_final = expected_parent_total + p0_new_count
    if len(ledger) != expected_final:
        _issue(issues, "FINAL_EFFECTIVE_SECURITY_COUNT_MISMATCH", "final-ledger", None,
               f"expected={expected_final}; actual={len(ledger)}")

    expected_am = [
        Interval("2017-12-26", "2019-03-12", "non_common"),
        Interval("2019-03-13", "2019-03-14", "common"),
    ]
    if ledger.get("838821611242754318") != expected_am:
        _issue(issues, "AM_TRANSITION_MISMATCH", "final-ledger",
               {"security_id": "838821611242754318", "ticker": "AM"},
               repr(ledger.get("838821611242754318")))
    expected_pds = [
        Interval("2006-07-05", "2010-06-01", "non_common"),
        Interval("2010-06-02", "2015-06-04", "common"),
    ]
    if ledger.get(pds) != expected_pds:
        _issue(issues, "PDS_TRANSITION_MISMATCH", "final-ledger",
               {"security_id": pds, "ticker": "PDS"}, repr(ledger.get(pds)))

    ambiguous_tickers = sorted(t for t, sids in parent_ticker_sids.items() if len(sids) > 1)
    report = {
        "schema": "champion.final-security-truth-corpus-validation/2",
        "status": "PASS_FINAL_TRUTH_CORPUS_EXECUTABLE" if not issues else "FAIL_FINAL_TRUTH_CORPUS_VALIDATION",
        "source_files": list(PARENT_FILES + CLEANUP_FILES + (P0_FILE,)),
        "parent_family_counts": family_counts,
        "parent_unique_security_count": len(parent_seen),
        "cleanup_target_count": len(cleanup_targets),
        "p0_new_adjudication_count": p0_new_count,
        "final_effective_security_count": len(ledger),
        "final_unresolved_count": len(unresolved),
        "ambiguous_parent_tickers_observed": ambiguous_tickers,
        "issue_count": len(issues),
        "issues": sorted(issues, key=lambda x: (
            x["code"], x["source"], x.get("security_id") or "", x.get("ticker") or "")),
        "performance_replay_executed": False,
    }
    return report, ledger


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manual", type=Path, default=MANUAL)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report, _ = validate_corpus(args.manual)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True), flush=True)
    return 0 if report["status"] == "PASS_FINAL_TRUTH_CORPUS_EXECUTABLE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
