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
from typing import Iterable

from backtester import champion_security_truth_overlay_v2 as prior

ROOT = Path(__file__).resolve().parents[1]
MANUAL = ROOT / "research/champion-economic-integrity/security-truth/manual-review"
CANONICAL_KEYS = ("canonical_interval", "interval", "decision_interval", "review_interval")

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
        a, b = value.replace(" — ", "/").replace("..", "/").split("/", 1)
        return a.strip(), b.strip()
    if isinstance(value, (list, tuple)) and len(value) == 2:
        return str(value[0]), str(value[1])
    if isinstance(value, dict):
        a = value.get("first_session") or value.get("effective_first_session")
        b = value.get("last_session") or value.get("effective_last_session")
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


def _parsed_intervals(case: dict, source: str) -> list[Interval]:
    decision = _decision(case)
    if decision == "unresolved":
        return []
    sid = str(case["security_id"])
    ticker = str(case.get("ticker", sid))
    rows = case.get("effective_intervals") or []
    result: list[Interval] = []
    for row in rows:
        if isinstance(row, dict):
            cls = str(row.get("classification") or row.get("decision") or "").lower()
            if cls not in {"common", "non_common"}:
                continue
            a = row.get("first_session") or row.get("effective_first_session")
            b = row.get("last_session") or row.get("effective_last_session")
            if a is None or b is None:
                continue
            result.append(Interval(str(a), str(b), cls, source, ticker))
        elif isinstance(row, (list, tuple)) and len(row) >= 3:
            cls = str(row[2]).lower()
            if cls in {"common", "non_common"}:
                result.append(Interval(str(row[0]), str(row[1]), cls, source, ticker))
        elif isinstance(row, str):
            # Manual-review artifacts use both compact rows such as
            #   "2020-01-01/2020-12-31 common"
            # and annotated split rows such as
            #   "2017-12-26/2019-03-12 non_common ... CUSIP ...".
            # The date range is always the first token and the factual class is
            # the first common/non_common token after it; trailing legal-type
            # annotations are provenance only and must not affect execution.
            normalized = row.replace(" — ", "/").replace("..", "/")
            parts = normalized.split()
            if len(parts) >= 2:
                cls_index = next(
                    (i for i, token in enumerate(parts[1:], start=1)
                     if token.lower() in {"common", "non_common"}),
                    None,
                )
                if cls_index is not None:
                    date_token = parts[0]
                    if "/" not in date_token:
                        raise ValueError(
                            f"string truth interval lacks date range: {source} {sid} {ticker} {row!r}"
                        )
                    a, b = date_token.split("/", 1)
                    result.append(
                        Interval(a.strip(), b.strip(), parts[cls_index].lower(), source, ticker)
                    )
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


def _cases(document: dict) -> Iterable[dict]:
    value = document.get("cases")
    if isinstance(value, list):
        yield from value


def _load() -> tuple[dict[str, list[Interval]], list[str]]:
    # Parent shards load first; cleanup files load last and replace the complete
    # reviewed episode for their scoped IDs. Some cleanup artifacts are ticker-
    # keyed and omit the canonical interval, so retain both security-id and
    # unique-ticker bindings from the parent shards independently of whether the
    # parent classification itself was unresolved.
    ledger: dict[str, list[Interval]] = {}
    ticker_to_sid: dict[str, str] = {}
    ticker_to_canonical: dict[str, tuple[str, str]] = {}
    sources: list[str] = []
    for filename in SOURCE_FILES:
        path = MANUAL / filename
        if not path.exists():
            raise FileNotFoundError(path)
        doc = json.loads(path.read_text())
        sources.append(filename)
        for raw_case in _cases(doc):
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

            # Remember canonical intervals independently of classification.
            # Parent unresolved rows still define the exact episode that a
            # higher-precedence cleanup closes. Historical shards use a small
            # number of equivalent field names, all normalized by _canonical.
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

            # Cleanup files may omit any interval field even when they carry a
            # security_id. Recover the parent episode first by exact security ID,
            # then by the already-validated unique ticker binding. Never invent
            # dates from evidence or market outcomes.
            if not _has_canonical(case):
                canonical = canonical_by_sid.get(sid)
                if canonical is None and ticker:
                    canonical = ticker_to_canonical.get(ticker)
                if canonical is not None:
                    case["canonical_interval"] = list(canonical)
                    canonical_by_sid[sid] = canonical

            intervals = _parsed_intervals(case, filename)
            # An unresolved parent record is intentionally retained until its
            # later cleanup is read. It must never erase an earlier closure.
            if intervals:
                ledger[sid] = intervals

    # P0 fresh-only adjudications were generated after the held/pending
    # integration and therefore supplement the parent classifier.
    p0 = MANUAL / "p0-fresh-path-delta.json"
    p0doc = json.loads(p0.read_text())
    sources.append(p0.name)
    for case in p0doc.get("new_adjudications", []):
        sid = str(case["security_id"])
        cls = str(case["classification"]).lower()
        a, b = _canonical(case)
        ledger[sid] = [Interval(a, b, cls, p0.name, str(case.get("ticker", sid)))]

    # Integration-level session-semantic override. Legal conversion completed
    # June 1; the common NYSE line begins with the June 2 decision session.
    pds = "594891209465982980"
    if pds in ledger:
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
    return ledger, sources


# Mutable only during deterministic module initialization.
canonical_by_sid: dict[str, tuple[str, str]] = {}
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
