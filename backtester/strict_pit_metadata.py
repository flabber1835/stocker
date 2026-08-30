#!/usr/bin/env python3
"""Causal metadata authorities for strict historical certification.

This module deliberately does not read SHARADAR_TICKERS.  Historical security
identity is derived from the observed SEP tape, issuer changes are derived from
strict-prior SEC evidence, security type is positive-only SEC/EDGAR evidence,
and exchange is non-authoritative.
"""
from __future__ import annotations

import bisect
import csv
import gzip
import hashlib
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

import pandas as pd


def _norm_int(value) -> str | None:
    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return str(int(float(text)))
    except (TypeError, ValueError, OverflowError):
        return text


def _sid(ticker: str, first_observed_session: str, episode: int) -> str:
    payload = f"PIT_SECURITY_V1|{ticker}|{first_observed_session}|{episode}".encode()
    # Numeric text preserves the production code's deterministic lexical/numeric
    # identity behavior while depending only on facts known when the episode begins.
    return str(int(hashlib.sha256(payload).hexdigest()[:15], 16))


@dataclass(frozen=True)
class IdentityEpisode:
    ticker: str
    first_session: str
    sid: str
    episode: int
    prior_cik: str | None


class CausalIdentityResolver:
    """Resolve ticker/session to a causal price-tape security episode."""

    def __init__(self, episodes: Mapping[str, Sequence[IdentityEpisode]], change_dates: Mapping[str, Sequence[str]]):
        self.episodes = {k: tuple(v) for k, v in episodes.items()}
        self.change_dates = {k: tuple(v) for k, v in change_dates.items()}

    def resolve(self, ticker: str, session: str) -> str | None:
        ticker = str(ticker)
        rows = self.episodes.get(ticker, ())
        if not rows:
            return None
        if session < rows[0].first_session:
            return None
        # A CIK change becomes usable strictly after its filing date.
        idx = bisect.bisect_left(self.change_dates.get(ticker, ()), str(session))
        idx = min(idx, len(rows) - 1)
        row = rows[idx]
        return row.sid if str(session) >= row.first_session else rows[max(0, idx - 1)].sid


class CausalIssuerAuthority:
    """Latest SEC issuer CIK filed strictly before a decision session."""

    def __init__(self, cik_path: Path):
        frame = pd.read_csv(cik_path, compression="gzip", low_memory=False)
        required = {"filing_date", "ticker", "issuer_cik"}
        missing = required - set(frame.columns)
        if missing:
            raise RuntimeError(f"SEC CIK evidence missing columns: {sorted(missing)}")
        self.dates: dict[str, list[str]] = defaultdict(list)
        self.values: dict[str, list[str]] = defaultdict(list)
        frame = frame.sort_values(["ticker", "filing_date"], kind="mergesort")
        for row in frame.itertuples(index=False):
            ticker = str(row.ticker).strip()
            filed = str(row.filing_date)[:10]
            cik = _norm_int(row.issuer_cik)
            if ticker and filed and cik is not None:
                self.dates[ticker].append(filed)
                self.values[ticker].append(cik)

    def strict_prior_cik(self, ticker: str, session: str) -> str | None:
        ticker = str(ticker)
        dates = self.dates.get(ticker, ())
        index = bisect.bisect_left(dates, str(session)) - 1
        return self.values[ticker][index] if index >= 0 else None

    def issuer(self, security_id: str, ticker: str, session: str) -> tuple[str, str]:
        cik = self.strict_prior_cik(ticker, session)
        if cik is None:
            return (
                f"SEC_UNKNOWN:{security_id}",
                "SEC_STRICT_PRIOR_UNKNOWN_SINGLETON",
            )
        return f"SEC_CIK:{cik}", "SEC_CIK_STRICT_PRIOR"


def _price_dates(sharadar_root: Path, start_year: int, end_year: int) -> dict[str, list[str]]:
    dates: dict[str, list[str]] = defaultdict(list)
    for year in range(start_year, end_year + 1):
        candidates = sorted(sharadar_root.glob(f"SHARADAR_SEP_{year}.csv*.gz"))
        if not candidates:
            continue
        path = candidates[0]
        frame = pd.read_csv(path, usecols=["ticker", "date"], low_memory=False)
        frame = frame.dropna(subset=["ticker", "date"])
        frame["ticker"] = frame["ticker"].astype(str)
        frame["date"] = frame["date"].astype(str).str[:10]
        frame = frame.drop_duplicates(["ticker", "date"], keep="last")
        for ticker, group in frame.groupby("ticker", sort=False):
            dates[str(ticker)].extend(group["date"].tolist())
    for ticker in list(dates):
        dates[ticker] = sorted(set(dates[ticker]))
    return dates


def _cik_changes(cik_path: Path) -> tuple[dict[str, list[tuple[str, str]]], dict[str, list[str]]]:
    frame = pd.read_csv(cik_path, compression="gzip", low_memory=False)
    required = {"filing_date", "ticker", "issuer_cik"}
    missing = required - set(frame.columns)
    if missing:
        raise RuntimeError(f"SEC CIK evidence missing columns: {sorted(missing)}")
    events: dict[str, list[tuple[str, str]]] = defaultdict(list)
    changes: dict[str, list[str]] = defaultdict(list)
    frame = frame.sort_values(["ticker", "filing_date"], kind="mergesort")
    for ticker, group in frame.groupby("ticker", sort=False):
        prior = None
        seen = []
        for row in group.itertuples(index=False):
            filed = str(row.filing_date)[:10]
            cik = _norm_int(row.issuer_cik)
            if not filed or cik is None:
                continue
            events[str(ticker)].append((filed, cik))
            if prior is None:
                prior = cik
            elif cik != prior:
                seen.append(filed)
                prior = cik
        changes[str(ticker)] = sorted(set(seen))
    return events, changes


def build_causal_metadata(
    *,
    sharadar_root: Path,
    cik_path: Path,
    SecurityMeta,
    start_year: int = 1997,
    end_year: int = 2026,
):
    """Build SecurityMeta and resolver without current TICKERS authority."""
    price_dates = _price_dates(sharadar_root, start_year, end_year)
    cik_events, change_dates = _cik_changes(cik_path)
    episodes: dict[str, list[IdentityEpisode]] = defaultdict(list)
    meta = {}
    canonical = {}

    for ticker, observed in sorted(price_dates.items()):
        if not observed:
            continue
        cutoffs = change_dates.get(ticker, [])
        starts = [observed[0]]
        for cutoff in cutoffs:
            i = bisect.bisect_right(observed, cutoff)
            if i < len(observed):
                starts.append(observed[i])
        starts = sorted(set(starts))
        for episode, first in enumerate(starts):
            prior_rows = [(d, c) for d, c in cik_events.get(ticker, ()) if d < first]
            prior_cik = prior_rows[-1][1] if prior_rows else None
            sid = _sid(ticker, first, episode)
            item = IdentityEpisode(ticker, first, sid, episode, prior_cik)
            episodes[ticker].append(item)
            meta[sid] = SecurityMeta(
                security_id=sid,
                ticker=ticker,
                category=None,
                permaticker=None,
                related_tickers=(),
                first_session=first,
                last_session=None,
                exchange=None,
                exchange_authoritative=False,
            )
            canonical[sid] = ticker

    if not meta:
        raise RuntimeError("strict PIT identity construction found no historical price-tape securities")
    resolver = CausalIdentityResolver(episodes, change_dates)
    sectors = {sid: None for sid in meta}
    audit = {
        "identity_authority": "historical SEP ticker observations plus strict-prior SEC CIK-change episode boundaries",
        "security_ids": len(meta),
        "tickers": len(episodes),
        "cik_change_episode_boundaries": sum(len(v) for v in change_dates.values()),
        "first_listing_authority": "first observed historical SEP price session",
        "last_listing_authority": "none; no future last-price date is admitted",
        "permaticker_authority": "none",
        "related_tickers_authority": "none",
        "exchange_authority": "none/non-authoritative",
    }
    return meta, sectors, resolver, canonical, audit


class SecurityTypeAuthority:
    """Strict-prior positive-only SEC/EDGAR common-equity authority."""

    def __init__(self, positive_path: Path, manual_audit_path: Path, pit_model):
        positive = pd.read_csv(positive_path, compression="gzip", low_memory=False)
        required = {"ticker", "filed", "cik"}
        missing = required - set(positive.columns)
        if missing:
            raise RuntimeError(f"SEC security-type evidence missing columns: {sorted(missing)}")
        self.by_ticker: dict[str, list[tuple[str, str | None]]] = defaultdict(list)
        positive = positive.sort_values(["ticker", "filed"], kind="mergesort")
        for row in positive.itertuples(index=False):
            ticker = str(row.ticker).strip().upper()
            filed = str(row.filed)[:10]
            cik = _norm_int(row.cik)
            if ticker and filed:
                self.by_ticker[ticker].append((filed, cik))
        self.dates_by_ticker = {
            ticker: tuple(filed for filed, _cik in rows)
            for ticker, rows in self.by_ticker.items()
        }
        self.first_positive_by_ticker_cik: dict[tuple[str, str | None], str] = {}
        for ticker, rows in self.by_ticker.items():
            for filed, cik in rows:
                self.first_positive_by_ticker_cik.setdefault((ticker, cik), filed)
        self.manual: dict[tuple[str, str], str] = {}
        if manual_audit_path.exists():
            manual = pd.read_csv(manual_audit_path, low_memory=False)
            for row in manual.itertuples(index=False):
                if str(getattr(row, "admission", "")) != "admitted":
                    continue
                ticker = str(getattr(row, "orion_ticker", "")).strip().upper()
                session = str(getattr(row, "buy_date", ""))[:10]
                resolved = str(getattr(row, "resolved_as", "")).strip().lower()
                if ticker and session and resolved in {"common", "non_common"}:
                    prior = self.manual.get((ticker, session))
                    if prior is not None and prior != resolved:
                        raise RuntimeError(f"contradictory manual security-type evidence for {(ticker, session)}")
                    self.manual[(ticker, session)] = resolved
        self.pit_model = pit_model
        self.auto_common = 0
        self.manual_common = 0
        self.manual_non_common = 0
        self.unknown = 0

    def _strict_prior_cik(self, ticker: str, session: str) -> str | None:
        model = self.pit_model
        return model._strict_prior(
            model.cik_dates.get(ticker, ()), model.cik_values.get(ticker, ()), session
        )

    def classify(self, ticker: str, session: str) -> tuple[str, str]:
        ticker = str(ticker).upper()
        manual = self.manual.get((ticker, str(session)))
        if manual == "common":
            self.manual_common += 1
            return "common", "MANUAL_EXACT_SESSION_COMMON"
        if manual == "non_common":
            self.manual_non_common += 1
            return "non_common", "MANUAL_EXACT_SESSION_NON_COMMON"

        dates = self.dates_by_ticker.get(ticker, ())
        if bisect.bisect_left(dates, str(session)):
            cik = self._strict_prior_cik(ticker, str(session))
            first = self.first_positive_by_ticker_cik.get((ticker, cik))
            if cik is None:
                first = dates[0]
            if first is not None and first < str(session):
                self.auto_common += 1
                return "common", "SEC_POSITIVE_STRICT_PRIOR_CIK_MATCH"
            self.unknown += 1
            return "unknown", "SEC_POSITIVE_STRICT_PRIOR_CIK_MISMATCH"
        self.unknown += 1
        return "unknown", "NO_STRICT_PRIOR_POSITIVE_EVIDENCE"

    def category(self, ticker: str, session: str) -> str | None:
        classification, _source = self.classify(ticker, session)
        if classification == "common":
            return "SEC Common Stock"
        if classification == "non_common":
            return "SEC Non-Common"
        return None

    def audit(self) -> dict:
        return {
            "authority": "SEC/EDGAR dated common/ordinary-equity evidence; filing/evidence date strictly prior to decision session",
            "automatic_positive_evidence_tickers": len(self.by_ticker),
            "manual_exact_session_classifications": len(self.manual),
            "observations_auto_common": self.auto_common,
            "observations_manual_common": self.manual_common,
            "observations_manual_non_common": self.manual_non_common,
            "observations_unknown_ineligible": self.unknown,
            "unknown_policy": "ineligible",
        }


def authority_audit(*, identity: dict, security_type: dict) -> dict:
    return {
        "schema": "backtester.metadata-authority-audit/1",
        "certification_mode": "strict-D",
        "economically_active_fields": {
            "security_identity": identity["identity_authority"],
            "ticker": "historical SEP row ticker on the simulated session",
            "listing_existence": "observed historical SEP tape; terminal lifecycle from causal PIT ACTIONS/terminal evidence",
            "issuer_grouping": "strict-prior SEC CIK; unknown issuer is a security singleton",
            "sector_grouping": "strict-prior SEC CIK -> strict-prior SEC SIC -> frozen FF12; unknown is singleton",
            "security_type": security_type["authority"],
            "exchange": "non-authoritative and therefore economically inert",
            "prices": "historical SEP raw/derived causal price domains",
            "corporate_actions": "PIT ACTIONS plus frozen causal terminal terms",
            "defensive_cash": "actual BIL when causally available; previous completed calendar month GS3M fallback",
        },
        "fallbacks": {
            "issuer_unknown": "security singleton",
            "sector_unknown": "security singleton",
            "security_type_unknown": "ineligible",
            "exchange_unknown": "non-authoritative/inert",
            "pre_BIL_cash": "strict-lag FRED GS3M",
        },
        "identity_statistics": identity,
        "security_type_statistics": security_type,
        "current_SHARADAR_TICKERS_economically_active_fields": [],
        "forbidden_current_SHARADAR_TICKERS_fields": [
            "permaticker", "category", "relatedtickers", "firstpricedate",
            "lastpricedate", "sector", "exchange",
        ],
        "hard_fail_if_current_SHARADAR_TICKERS_becomes_economically_active": True,
    }
