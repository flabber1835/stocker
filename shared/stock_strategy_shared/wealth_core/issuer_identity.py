"""Point-in-time issuer identity from dated SEC ownership filings.

This module intentionally does not consume Sharadar ``relatedtickers``.  That
field is a present-day relationship snapshot and can contain securities that
did not exist at the historical decision date.  SEC issuer CIK observations
are instead resolved using only filings that were already dated strictly
before the decision session.

The strict-before rule is deliberate: the structured Form 3/4/5 quarterly
archives expose FILING_DATE but not an EDGAR acceptance timestamp.  Without an
acceptance timestamp, a filing dated on decision day is not treated as known
at that day's close.
"""

from __future__ import annotations

import csv
from bisect import bisect_left
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterable, Mapping

SEC_CIK_SOURCE = "SEC_CIK"
PERMATICKER_PIT_FALLBACK_SOURCE = "PERMATICKER_PIT_FALLBACK"

_REQUIRED_CSV_FIELDS = frozenset(
    {
        "filing_date",
        "issuer_cik",
        "issuer_trading_symbol",
        "accession_number",
        "document_type",
        "archive",
    }
)
_SOURCE_MEMBER_FIELDS = ("submission_member", "source_member")
_SOURCE_ROW_FIELDS = ("row_number", "source_row")


def _parse_date(value: date | str, *, field: str) -> date:
    if isinstance(value, date):
        return value
    text = str(value).strip()
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"invalid {field} date: {value!r}") from exc


def normalize_sec_ticker(value: object) -> str:
    """Normalize only case/outer whitespace; do not rewrite punctuation."""

    ticker = str(value or "").strip().upper()
    if not ticker:
        raise ValueError("SEC issuer evidence requires a non-empty ticker")
    return ticker


def normalize_sec_cik(value: object) -> str:
    text = str(value or "").strip()
    if not text or not text.isdigit() or len(text) > 10:
        raise ValueError(f"invalid SEC issuer CIK: {value!r}")
    return text.zfill(10)


@dataclass(frozen=True, slots=True)
class SecIssuerEvidence:
    ticker: str
    issuer_cik: str
    filing_date: date
    accession_number: str
    document_type: str
    archive: str
    source_member: str
    source_row: int

    @classmethod
    def from_mapping(cls, row: Mapping[str, object]) -> "SecIssuerEvidence":
        source_row_raw = row.get("row_number", row.get("source_row", ""))
        try:
            source_row = int(str(source_row_raw).strip())
        except ValueError as exc:
            raise ValueError(f"invalid SEC source row: {source_row_raw!r}") from exc
        if source_row < 1:
            raise ValueError(f"invalid SEC source row: {source_row!r}")

        accession = str(row.get("accession_number", "") or "").strip()
        if not accession:
            raise ValueError("SEC issuer evidence requires accession_number")

        return cls(
            ticker=normalize_sec_ticker(row.get("issuer_trading_symbol", "")),
            issuer_cik=normalize_sec_cik(row.get("issuer_cik", "")),
            filing_date=_parse_date(row.get("filing_date", ""), field="filing"),
            accession_number=accession,
            document_type=str(row.get("document_type", "") or "").strip(),
            archive=str(row.get("archive", "") or "").strip(),
            source_member=str(
                row.get("submission_member", row.get("source_member", "")) or ""
            ).strip(),
            source_row=source_row,
        )

    def provenance_key(self) -> tuple[str, str, str, str, int]:
        return (
            self.accession_number,
            self.document_type,
            self.archive,
            self.source_member,
            self.source_row,
        )


@dataclass(frozen=True, slots=True)
class IssuerResolution:
    issuer_key: str
    source: str
    ticker: str
    issuer_cik: str
    filing_date: date
    accession_number: str
    document_type: str
    archive: str
    source_member: str
    source_row: int

    @classmethod
    def from_evidence(cls, evidence: SecIssuerEvidence) -> "IssuerResolution":
        return cls(
            issuer_key=f"CIK:{evidence.issuer_cik}",
            source=SEC_CIK_SOURCE,
            ticker=evidence.ticker,
            issuer_cik=evidence.issuer_cik,
            filing_date=evidence.filing_date,
            accession_number=evidence.accession_number,
            document_type=evidence.document_type,
            archive=evidence.archive,
            source_member=evidence.source_member,
            source_row=evidence.source_row,
        )


@dataclass(frozen=True, slots=True)
class IssuerKeyResolution:
    issuer_key: str
    source: str
    evidence: IssuerResolution | None


@dataclass(frozen=True, slots=True)
class _TimelineEntry:
    filing_date: date
    evidence: SecIssuerEvidence | None


class SecIssuerResolver:
    """Resolve issuer CIK causally for a historical ticker/session.

    Evidence is compacted to one deterministic provenance witness for each
    (ticker, filing_date, CIK).  If multiple distinct CIKs are observed for the
    same ticker on the same latest causal filing date, that date is ambiguous
    and resolution fails closed instead of falling back to older evidence.
    """

    def __init__(self, evidence: Iterable[SecIssuerEvidence]) -> None:
        # Keep only a deterministic witness for duplicate same-CIK observations.
        witnesses: dict[tuple[str, date, str], SecIssuerEvidence] = {}
        ciks_by_ticker_date: dict[tuple[str, date], set[str]] = {}

        for raw in evidence:
            item = SecIssuerEvidence(
                ticker=normalize_sec_ticker(raw.ticker),
                issuer_cik=normalize_sec_cik(raw.issuer_cik),
                filing_date=_parse_date(raw.filing_date, field="filing"),
                accession_number=str(raw.accession_number).strip(),
                document_type=str(raw.document_type).strip(),
                archive=str(raw.archive).strip(),
                source_member=str(raw.source_member).strip(),
                source_row=int(raw.source_row),
            )
            if not item.accession_number:
                raise ValueError("SEC issuer evidence requires accession_number")
            if item.source_row < 1:
                raise ValueError(f"invalid SEC source_row: {item.source_row!r}")

            td = (item.ticker, item.filing_date)
            ciks_by_ticker_date.setdefault(td, set()).add(item.issuer_cik)
            key = (item.ticker, item.filing_date, item.issuer_cik)
            prior = witnesses.get(key)
            if prior is None or item.provenance_key() < prior.provenance_key():
                witnesses[key] = item

        entries_by_ticker: dict[str, list[_TimelineEntry]] = {}
        for (ticker, filing_date), ciks in ciks_by_ticker_date.items():
            if len(ciks) != 1:
                evidence_item = None
            else:
                cik = next(iter(ciks))
                evidence_item = witnesses[(ticker, filing_date, cik)]
            entries_by_ticker.setdefault(ticker, []).append(
                _TimelineEntry(filing_date=filing_date, evidence=evidence_item)
            )

        self._entries: dict[str, tuple[_TimelineEntry, ...]] = {}
        self._dates: dict[str, tuple[date, ...]] = {}
        for ticker, entries in entries_by_ticker.items():
            ordered = tuple(sorted(entries, key=lambda item: item.filing_date))
            self._entries[ticker] = ordered
            self._dates[ticker] = tuple(item.filing_date for item in ordered)

    @classmethod
    def from_csv(cls, path: str | Path) -> "SecIssuerResolver":
        csv_path = Path(path)
        with csv_path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            fields = set(reader.fieldnames or ())
            missing = sorted(_REQUIRED_CSV_FIELDS - fields)
            if not any(name in fields for name in _SOURCE_MEMBER_FIELDS):
                missing.append("submission_member")
            if not any(name in fields for name in _SOURCE_ROW_FIELDS):
                missing.append("row_number")
            if missing:
                raise ValueError(
                    "SEC observations CSV missing required columns: " + ", ".join(missing)
                )
            return cls(SecIssuerEvidence.from_mapping(row) for row in reader)

    def resolve(
        self,
        ticker: str,
        decision_session: date | str,
        *,
        evidence_not_before: date | str | None = None,
    ) -> IssuerResolution | None:
        normalized_ticker = normalize_sec_ticker(ticker)
        session = _parse_date(decision_session, field="decision_session")
        lower_bound = (
            None
            if evidence_not_before is None
            else _parse_date(evidence_not_before, field="evidence_not_before")
        )
        if lower_bound is not None and lower_bound >= session:
            return None

        dates = self._dates.get(normalized_ticker)
        if not dates:
            return None

        # Strictly earlier filing date: same-day filings are not assumed known.
        index = bisect_left(dates, session) - 1
        if index < 0:
            return None
        entry = self._entries[normalized_ticker][index]
        if lower_bound is not None and entry.filing_date < lower_bound:
            return None
        if entry.evidence is None:
            # Latest causal date is ambiguous.  Do not resurrect a stale CIK.
            return None
        return IssuerResolution.from_evidence(entry.evidence)

    def issuer_key_for(
        self,
        ticker: str,
        decision_session: date | str,
        *,
        permaticker: str | int,
        evidence_not_before: date | str | None = None,
    ) -> IssuerKeyResolution:
        resolved = self.resolve(
            ticker,
            decision_session,
            evidence_not_before=evidence_not_before,
        )
        if resolved is not None:
            return IssuerKeyResolution(
                issuer_key=resolved.issuer_key,
                source=SEC_CIK_SOURCE,
                evidence=resolved,
            )

        fallback = str(permaticker).strip()
        if not fallback:
            raise ValueError("permaticker is required for PIT issuer fallback")
        return IssuerKeyResolution(
            issuer_key=f"P:{fallback}",
            source=PERMATICKER_PIT_FALLBACK_SOURCE,
            evidence=None,
        )
