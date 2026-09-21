"""Correct dated evidence handling without mutating retained source data."""
from __future__ import annotations

import csv
from datetime import date, datetime
from functools import lru_cache
import gzip
import hashlib
from pathlib import Path

POSITIVE_HASH = "75beead9fa83b1cdef3722d89e66edcd46d26c2ab6eff9d7ad1178fda30587f1"
MANUAL_HASH = "0ce3b763072dde5864e27cbba7ec513b29010f1b05201e6e1155006fbd2a8cb1"
FORMATION_END = "2006-07-06"

# Explicit episode identities from the retained manual review and SEC sources.
# These links are bounded diagnostic inputs, not a general ticker normalizer.
LINKS = {
    "214820292338870148": ("CHAP1", "CHAP", "1319048", None),
    "353685636371040898": ("AVL1", "AVL", "701650", None),
    "840588175708298328": ("VOLT2", "VOL", "103872", None),
    "1099247927332588244": ("FTI1", "FTI", "1135152", None),
    "88378928586164151": ("WEBX1", "WEBX", "1109935", None),
    "1040633074096912075": ("FALB", "FAL", "889211", "2005-08-15"),
    "788900523736619527": ("LFCHY", "LFC", "1268896", "2006-05-30"),
}


@lru_cache(maxsize=32768)
def filing_date(value: str) -> str:
    """Validate first, then return an order-preserving date representation."""
    value = value.strip()
    if len(value) == 10 and value[4] == "-" and value[7] == "-":
        return date.fromisoformat(value).isoformat()
    return datetime.strptime(value, "%d-%b-%Y").date().isoformat()


def cik(value: str) -> str | None:
    value = str(value).strip()
    return str(int(value)) if value else None


def verify(path: Path, expected: str) -> None:
    with path.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != expected:
            raise ValueError("retained classification source differs: " + str(path))


class Classifier:
    def __init__(self, positive, manual):
        self.first = {}
        self.first_any = {}
        self.manual = {}
        for row in positive:
            ticker = row["ticker"].strip().upper()
            filed = filing_date(row["filed"])
            key = (ticker, cik(row["cik"]))
            self.first[key] = min(filed, self.first.get(key, filed))
            self.first_any[ticker] = min(filed, self.first_any.get(ticker, filed))
        for row in manual:
            if row["admission"] != "admitted":
                continue
            session = filing_date(row["buy_date"])
            if filing_date(row["evidence_date"]) >= session:
                raise ValueError("manual evidence does not precede decision")
            value = row["resolved_as"]
            if value not in {"common", "non_common"}:
                raise ValueError("invalid admitted manual classification")
            key = (row["orion_ticker"].strip().upper(), session)
            if key in self.manual and self.manual[key] != value:
                raise ValueError("contradictory manual classification")
            self.manual[key] = value

    @classmethod
    def load(cls, directory):
        positive = Path(directory) / "SEC_SECURITY_TYPE_POSITIVE_EVIDENCE.csv.gz"
        manual = Path(directory) / "SEC_SECURITY_TYPE_MANUAL_ADMISSION_AUDIT.csv"
        verify(positive, POSITIVE_HASH)
        verify(manual, MANUAL_HASH)
        with gzip.open(positive, "rt", encoding="utf-8", newline="") as p:
            with manual.open(encoding="utf-8", newline="") as m:
                return cls(csv.DictReader(p), csv.DictReader(m))

    def dated(self, ticker, issuer, session):
        manual = self.manual.get((ticker, session))
        if manual is not None:
            return manual
        issuer_cik = cik(issuer.removeprefix("SEC_CIK:")) if issuer.startswith("SEC_CIK:") else None
        first = (self.first.get((ticker, issuer_cik)) if issuer_cik is not None
                 else self.first_any.get(ticker))
        return "common" if first is not None and first < session else "unknown"

    def linked(self, row):
        session = row["session"]
        link = LINKS.get(row["security_id"])
        if link is None or not "2006-01-03" <= session <= FORMATION_END:
            return None
        ticker, symbol, issuer, manual_date = link
        if row["ticker"] != ticker:
            raise ValueError("reviewed security identity changed ticker")
        known_issuer = row["issuer_id"]
        if known_issuer.startswith("SEC_CIK:") and cik(known_issuer[8:]) != issuer:
            raise ValueError("reviewed security identity contradicts issuer")
        first = manual_date or self.first.get((symbol, issuer))
        return "common" if first is not None and first < session else None

    def apply(self, row, mode):
        if mode not in {"dates", "seven", "combined"}:
            raise ValueError("unknown diagnostic mode")
        result = dict(row)
        value = (self.dated(row["ticker"], row["issuer_id"], row["session"])
                 if mode != "seven" else row["security_type"])
        source = "RESEARCH_PARSED_DATED_EVIDENCE" if mode != "seven" else row["security_type_source"]
        if mode != "dates":
            linked = self.linked(row)
            if linked is not None:
                value, source = linked, "RESEARCH_SEVEN_EPISODE_LINK"
        result.update(security_type=value, security_type_source=source,
                      security_type_eligible="1" if value == "common" else "0",
                      metadata_admitted="1" if value == "common" else "0")
        return result
