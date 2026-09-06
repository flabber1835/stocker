#!/usr/bin/env python3
"""Closed production-equivalent security-type truth overlay.

The manual-review corpus is authoritative for reviewed decision-relevant unknown
security episodes. Cleanup artifacts supersede their parent shard. This module
never consumes returns, ranks, portfolio outcomes, survival or future index
membership.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Iterable

from backtester import champion_security_truth_overlay_v2 as prior

ROOT = Path(__file__).resolve().parents[1]
MANUAL = ROOT / "research/champion-economic-integrity/security-truth/manual-review"

SOURCE_FILES = (
    "durable-shard-00.json", "durable-shard-01.json", "durable-shard-02.json",
    "durable-shard-03.json", "durable-shard-04.json", "durable-shard-05.json",
    "durable-shard-06.json", "durable-shard-07.json", "durable-shard-08.json",
    "durable-shard-09.json",
    "leadership-shard-00.json", "leadership-shard-01.json",
    "leadership-shard-02.json", "leadership-shard-03.json",
    "ranking-shard-00.json", "ranking-shard-01.json",
    # Higher-precedence factual cleanups.
    "durable-shard-06-cleanup.json", "durable-shard-07-cleanup.json",
    "durable-shard-09-cleanup.json", "leadership-shard-00-cleanup.json",
    "leadership-shard-01-cleanup.json", "ranking-shard-01-cleanup.json",
)
CASE_KEYS = ("cases", "reviews", "results")
CANONICAL_KEYS = ("canonical_interval", "interval", "decision_interval", "review_interval")
INTERVAL_RE = re.compile(
    r"^\s*(\d{4}-\d{2}-\d{2})/(\d{4}-\d{2}-\d{2})(?::|\s+)(common|non_common)\b",
    re.IGNORECASE,
)
EXPECTED_FINAL_SECURITY_COUNT = 696


@dataclass(frozen=True)
class Interval:
    first: str
    last: str
    classification: str
    source: str
    ticker: str


def _canonical(case: dict) -> tuple[str, str]:
    value = None
    for key in CANONICAL_KEYS:
        if case.get(key) is not None:
            value = case[key]
            break
    if isinstance(value, str):
        normalized = value.replace(" — ", "/").replace("..", "/")
        if "/" not in normalized:
            raise ValueError(f"unsupported canonical interval: {value!r}")
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
    raise ValueError(f"unsupported canonical interval: {value!r}")


def _has_canonical(case: dict) -> bool:
    return any(case.get(key) is not None for key in CANONICAL_KEYS)


def _decision(case: dict) -> str:
    return str(
        case.get("final_decision")
        or case.get("decision")
        or case.get("classification")
        or ""
    ).lower()


def _parse_one(row, decision: str, source: str, ticker: str) -> Interval | None:
    if isinstance(row, dict):
        cls = str(row.get("classification") or row.get("decision") or "").lower()
        a = (row.get("first_session") or row.get("effective_first_session")
             or row.get("start") or row.get("first"))
        b = (row.get("last_session") or row.get("effective_last_session")
             or row.get("end") or row.get("last"))
        if cls in {"common", "non_common"} and a is not None and b is not None:
            return Interval(str(a), str(b), cls, source, ticker)
        return None
    if isinstance(row, (list, tuple)):
        if len(row) >= 3:
            cls = str(row[2]).lower()
            if cls in {"common", "non_common"}:
                return Interval(str(row[0]), str(row[1]), cls, source, ticker)
        if len(row) == 2 and decision in {"common", "non_common"}:
            return Interval(str(row[0]), str(row[1]), decision, source, ticker)
        return None
    if isinstance(row, str):
        normalized = row.replace(" — ", "/").replace("..", "/")
        match = INTERVAL_RE.match(normalized)
        if match:
            return Interval(match.group(1), match.group(2), match.group(3).lower(), source, ticker)
    return None


def _parsed_intervals(case: dict, source: str) -> list[Interval]:
    decision = _decision(case)
    if decision == "unresolved":
        return []
    sid = str(case["security_id"])
    ticker = str(case.get("ticker", sid))
    raw_rows = case.get("effective_intervals")
    if raw_rows is None:
        rows = []
    elif isinstance(raw_rows, list):
        rows = raw_rows
    else:
        raise ValueError(f"effective_intervals is not a list: {source} {sid} {ticker}")

    result: list[Interval] = []
    for index, row in enumerate(rows):
        parsed = _parse_one(row, decision, source, ticker)
        if parsed is None:
            raise ValueError(
                f"unparseable final truth interval: {source} {sid} {ticker} "
                f"effective_intervals[{index}]={row!r}"
            )
        result.append(parsed)

    if result:
        return result
    if decision in {"common", "non_common"}:
        if not _has_canonical(case):
            raise ValueError(
                f"resolved case lacks canonical interval after parent recovery: "
                f"{source} {sid} {ticker} {decision}"
            )
        a, b = _canonical(case)
        return [Interval(a, b, decision, source, ticker)]
    raise ValueError(f"resolved case lacks executable intervals: {source} {sid} {ticker} {decision}")


def _cases(document: dict, source: str) -> Iterable[dict]:
    found = [(key, document.get(key)) for key in CASE_KEYS if key in document]
    usable = [(key, value) for key, value in found if isinstance(value, list)]
    if len(usable) != 1:
        raise ValueError(
            f"manual-review source must expose exactly one case collection: "
            f"{source} observed={[(key, type(value).__name__) for key, value in found]}"
        )
    yield from usable[0][1]


def _load() -> tuple[dict[str, list[Interval]], list[str]]:
    ledger: dict[str, list[Interval]] = {}
    unresolved: set[str] = set()
    ticker_to_sid: dict[str, str] = {}
    canonical_by_sid: dict[str, tuple[str, str]] = {}
    ticker_to_canonical: dict[str, tuple[str, str]] = {}
    sources: list[str] = []

    for filename in SOURCE_FILES:
        path = MANUAL / filename
        if not path.exists():
            raise FileNotFoundError(path)
        doc = json.loads(path.read_text())
        sources.append(filename)
        for raw_case in _cases(doc, filename):
            if not isinstance(raw_case, dict):
                raise ValueError(f"manual-review case is not an object: {filename} {raw_case!r}")
            case = dict(raw_case)
            ticker = str(case.get("ticker", ""))
            if "security_id" in case:
                sid = str(case["security_id"])
                if ticker:
                    previous = ticker_to_sid.get(ticker)
                    if previous is not None and previous != sid:
                        raise ValueError(f"ambiguous ticker/security binding: {ticker} {previous} {sid}")
                    ticker_to_sid[ticker] = sid
            else:
                sid = ticker_to_sid.get(ticker, "")
                if not sid:
                    raise ValueError(f"cleanup case lacks security_id and parent binding: {filename} {ticker}")
                case["security_id"] = sid

            if _has_canonical(case):
                canonical = _canonical(case)
                canonical_by_sid[sid] = canonical
                if ticker:
                    previous_canonical = ticker_to_canonical.get(ticker)
                    if previous_canonical is not None and previous_canonical != canonical:
                        raise ValueError(
                            f"ambiguous ticker/canonical binding: {ticker} "
                            f"{previous_canonical} {canonical}"
                        )
                    ticker_to_canonical[ticker] = canonical

            if not _has_canonical(case):
                canonical = canonical_by_sid.get(sid)
                if canonical is None and ticker:
                    canonical = ticker_to_canonical.get(ticker)
                if canonical is not None:
                    case["canonical_interval"] = list(canonical)
                    canonical_by_sid[sid] = canonical

            decision = _decision(case)
            intervals = _parsed_intervals(case, filename)
            if decision == "unresolved":
                unresolved.add(sid)
            elif intervals:
                ledger[sid] = intervals
                unresolved.discard(sid)

    p0 = MANUAL / "p0-fresh-path-delta.json"
    p0doc = json.loads(p0.read_text())
    sources.append(p0.name)
    for case in p0doc.get("new_adjudications", []):
        sid = str(case["security_id"])
        cls = str(case["classification"]).lower()
        if cls not in {"common", "non_common"}:
            raise ValueError(f"invalid P0 classification: {sid} {cls}")
        a, b = _canonical(case)
        ledger[sid] = [Interval(a, b, cls, p0.name, str(case.get("ticker", sid)))]
        unresolved.discard(sid)

    pds = "594891209465982980"
    if pds not in ledger:
        raise ValueError("PDS missing from final security truth ledger")
    ledger[pds] = [
        Interval("2006-07-05", "2010-06-01", "non_common", "FINAL_SECURITY_TRUTH_INTEGRATION.md", "PDS"),
        Interval("2010-06-02", "2015-06-04", "common", "FINAL_SECURITY_TRUTH_INTEGRATION.md", "PDS"),
    ]

    for sid, intervals in ledger.items():
        ordered = sorted(intervals, key=lambda x: x.first)
        for row in ordered:
            if row.classification not in {"common", "non_common"} or row.first > row.last:
                raise ValueError(f"invalid final truth interval: {sid} {row}")
        for left, right in zip(ordered, ordered[1:]):
            if right.first <= left.last:
                raise ValueError(f"overlapping final truth intervals: {sid} {left} {right}")
        ledger[sid] = ordered

    if unresolved:
        raise ValueError(f"final security truth unresolved IDs remain: {sorted(unresolved, key=int)}")
    if len(ledger) != EXPECTED_FINAL_SECURITY_COUNT:
        raise ValueError(
            f"final security truth count mismatch: expected={EXPECTED_FINAL_SECURITY_COUNT} actual={len(ledger)}"
        )

    expected_am = [
        ("2017-12-26", "2019-03-12", "non_common"),
        ("2019-03-13", "2019-03-14", "common"),
    ]
    actual_am = [(x.first, x.last, x.classification) for x in ledger["838821611242754318"]]
    if actual_am != expected_am:
        raise ValueError(f"AM transition mismatch: {actual_am}")

    return ledger, sources


FINAL_INTERVALS, FINAL_SOURCES = _load()


class SecurityTypeEstimate(prior.SecurityTypeEstimate):
    """Prior classifier plus the closed factual decision-relevant truth corpus."""

    def __init__(self, ledger: Path, scenario: str):
        super().__init__(ledger, scenario)
        self.final_truth_calls: dict[str, int] = {}

    def _final(self, security_id: str, session: str) -> Interval | None:
        for row in FINAL_INTERVALS.get(str(security_id), ()):
            if row.first <= str(session) <= row.last:
                return row
        return None

    def _classify(self, security_id: str, session: str, *, count: bool) -> str:
        row = self._final(str(security_id), str(session))
        if row is None:
            return super()._classify(str(security_id), str(session), count=count)
        if count:
            self.calls[row.classification] += 1
            sid = str(security_id)
            self.final_truth_calls[sid] = self.final_truth_calls.get(sid, 0) + 1
        return row.classification

    def provenance(self, security_id: str, session: str) -> dict[str, str]:
        row = self._final(str(security_id), str(session))
        if row is None:
            return super().provenance(str(security_id), str(session))
        return {
            "source_status": "PRODUCTION_EQUIVALENT_FACTUAL_TRUTH_CLOSED",
            "effective_first_session": row.first,
            "effective_last_session": row.last,
            "evidence_kind": "MANUAL_AUTHORITATIVE_LEGAL_SECURITY_TYPE",
            "evidence_source_ids": row.source,
            "evidence_timing_policy": "LATER_AUTHORITY_MAY_ESTABLISH_EARLIER_FACT_NO_OUTCOME_INFORMATION",
        }

    def summary(self) -> dict:
        result = super().summary()
        result.update(
            label="PRODUCTION_EQUIVALENT_FACTUAL_TRUTH_CLOSED",
            final_truth_security_count=len(FINAL_INTERVALS),
            final_truth_source_files=list(FINAL_SOURCES),
            final_truth_calls=dict(sorted(self.final_truth_calls.items())),
            unresolved_type_cases=0,
            certification_eligible=True,
        )
        return result
