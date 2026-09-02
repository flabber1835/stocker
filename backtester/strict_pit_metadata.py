#!/usr/bin/env python3
"""Causal metadata authorities for strict historical certification.

Historical security identity is derived from the observed SEP tape and causal
terminal evidence. SEC CIK is issuer evidence only: a CIK change can corroborate
an already-visible terminal/relisting boundary, but cannot create a security
identity episode by itself. Security type is positive-only SEC/EDGAR evidence,
and exchange is non-authoritative.
"""
from __future__ import annotations

import bisect
import csv
import gzip
import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

import pandas as pd


_TARGET_TERMINAL_ACTIONS = frozenset({
    "delisted",
    "acquisitionby",
    "mergerto",
    "bankruptcyliquidation",
    "regulatorydelisting",
    "voluntarydelisting",
})

IDENTITY_AUTHORITY = (
    "historical SEP tape continuity; new security episodes require causal "
    "terminal/relisting corroboration; SEC CIK is issuer evidence and cannot "
    "create a security episode by itself"
)


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
    """Stable numeric identity with chronological ordering within one ticker."""
    payload = f"PIT_SECURITY_V1|{ticker}|{first_observed_session}|0".encode()
    base = str(int(hashlib.sha256(payload).hexdigest()[:15], 16))
    # Episode zero keeps the original v1 identity. Later corroborated episodes
    # extend that id so the existing canonical resolver's lexical ordering is
    # chronological for multiple episodes of the same ticker.
    return base if episode == 0 else f"{base}{episode:04d}"


@dataclass(frozen=True)
class IdentityEpisode:
    ticker: str
    first_session: str
    sid: str
    episode: int
    prior_cik: str | None


@dataclass(frozen=True)
class CIKChange:
    filing_date: str
    prior_cik: str
    new_cik: str
    transition_count: int = 1


class CausalIdentityResolver:
    """Resolve ticker/session to a causal price-tape security episode."""

    def __init__(self, episodes: Mapping[str, Sequence[IdentityEpisode]], _change_dates=None):
        self.episodes = {k: tuple(v) for k, v in episodes.items()}
        self.starts = {
            ticker: tuple(row.first_session for row in rows)
            for ticker, rows in self.episodes.items()
        }

    def resolve(self, ticker: str, session: str) -> str | None:
        ticker = str(ticker)
        rows = self.episodes.get(ticker, ())
        if not rows:
            return None
        index = bisect.bisect_right(self.starts[ticker], str(session)) - 1
        return None if index < 0 else rows[index].sid


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


def _cik_changes(
    cik_path: Path,
) -> tuple[dict[str, list[tuple[str, str]]], dict[str, list[CIKChange]]]:
    frame = pd.read_csv(cik_path, compression="gzip", low_memory=False)
    required = {"filing_date", "ticker", "issuer_cik"}
    missing = required - set(frame.columns)
    if missing:
        raise RuntimeError(f"SEC CIK evidence missing columns: {sorted(missing)}")
    events: dict[str, list[tuple[str, str]]] = defaultdict(list)
    changes: dict[str, list[CIKChange]] = defaultdict(list)
    frame = frame.sort_values(["ticker", "filing_date"], kind="mergesort")
    for ticker, group in frame.groupby("ticker", sort=False):
        prior = None
        by_date: dict[str, list] = {}
        ticker_text = str(ticker)
        for row in group.itertuples(index=False):
            filed = str(row.filing_date)[:10]
            cik = _norm_int(row.issuer_cik)
            if not filed or cik is None:
                continue
            events[ticker_text].append((filed, cik))
            if prior is not None and cik != prior:
                if filed not in by_date:
                    by_date[filed] = [prior, cik, 1]
                else:
                    by_date[filed][1] = cik
                    by_date[filed][2] = int(by_date[filed][2]) + 1
            prior = cik
        changes[ticker_text] = [
            CIKChange(filed, values[0], values[1], int(values[2]))
            for filed, values in sorted(by_date.items())
        ]
    return events, changes


def _changes_as_of(
    changes: Mapping[str, Sequence[CIKChange]], as_of: str,
) -> dict[str, tuple[CIKChange, ...]]:
    """Exclude issuer evidence that did not exist by the audit horizon."""
    return {
        ticker: tuple(row for row in rows if row.filing_date <= as_of)
        for ticker, rows in changes.items()
    }


def _terminal_identity_evidence(
    sharadar_root: Path,
) -> tuple[dict[str, tuple[str, ...]], dict[str, tuple[str, ...]]]:
    """Load causal target-terminal dates used only to corroborate identity breaks."""
    root = sharadar_root.parent
    vendor: dict[str, set[str]] = defaultdict(set)
    actions_path = root / "PIT input data" / "ACTIONS_PIT_ONLY.csv.gz"
    if actions_path.is_file():
        frame = pd.read_csv(
            actions_path,
            compression="gzip",
            usecols=["date", "action", "ticker"],
            low_memory=False,
        )
        for row in frame.itertuples(index=False):
            action = str(row.action or "").strip().lower()
            ticker = str(row.ticker or "").strip()
            session = str(row.date)[:10]
            if ticker and session and action in _TARGET_TERMINAL_ACTIONS:
                vendor[ticker].add(session)

    exact: dict[str, set[str]] = defaultdict(set)
    exact_path = root / "backtester" / "data" / "causal-terminal-terms-v1.json"
    if exact_path.is_file():
        payload = json.loads(exact_path.read_text(encoding="utf-8"))
        for row in payload.get("records") or []:
            ticker = str(row.get("ticker") or "").strip()
            session = str(row.get("effective_session") or "")[:10]
            if ticker and session:
                exact[ticker].add(session)
    return (
        {ticker: tuple(sorted(rows)) for ticker, rows in vendor.items()},
        {ticker: tuple(sorted(rows)) for ticker, rows in exact.items()},
    )


def _between(dates: Sequence[str], left: str, right: str) -> tuple[str, ...]:
    start = bisect.bisect_left(dates, left)
    end = bisect.bisect_left(dates, right)
    return tuple(dates[start:end])


def _identity_boundary_classification(
    *,
    price_dates: Mapping[str, Sequence[str]],
    changes: Mapping[str, Sequence[CIKChange]],
    vendor_terminals: Mapping[str, Sequence[str]],
    exact_terminals: Mapping[str, Sequence[str]],
) -> tuple[dict[str, set[str]], list[dict], list[dict], dict]:
    market_sessions = sorted({session for rows in price_dates.values() for session in rows})
    market_index = {session: index for index, session in enumerate(market_sessions)}
    episode_starts: dict[str, set[str]] = {
        ticker: {str(rows[0])}
        for ticker, rows in price_dates.items()
        if rows
    }

    # Frozen exact terminal terms are independently authoritative episode
    # boundaries when the same ticker later reappears on the tape.
    frozen_terminal_starts: set[tuple[str, str]] = set()
    for ticker, terminals in exact_terminals.items():
        observed = tuple(price_dates.get(ticker, ()))
        if not observed:
            continue
        for terminal in terminals:
            after = bisect.bisect_right(observed, str(terminal))
            if 0 < after < len(observed):
                first_after = str(observed[after])
                episode_starts[ticker].add(first_after)
                frozen_terminal_starts.add((ticker, first_after))

    records: list[dict] = []
    blocking: list[dict] = []
    dispositions: dict[str, int] = defaultdict(int)

    for ticker in sorted(changes):
        observed = tuple(price_dates.get(ticker, ()))
        for change in changes[ticker]:
            record = {
                "ticker": str(ticker),
                "filing_date": str(change.filing_date),
                "prior_cik": str(change.prior_cik),
                "new_cik": str(change.new_cik),
                "same_day_transition_count": int(change.transition_count),
                "prior_price_session": "",
                "next_price_session": "",
                "skipped_market_sessions": "",
                "terminal_evidence": "",
                "disposition": "",
            }
            if change.prior_cik == change.new_cik:
                record["disposition"] = "SAME_DAY_CIK_OSCILLATION_REJECTED"
                dispositions[record["disposition"]] += 1
                records.append(record)
                continue
            if not observed:
                record["disposition"] = "NO_PRICE_TAPE_FOR_TICKER"
                dispositions[record["disposition"]] += 1
                records.append(record)
                continue
            next_index = bisect.bisect_right(observed, change.filing_date)
            prior_index = next_index - 1
            if prior_index < 0 or next_index >= len(observed):
                record["disposition"] = "OUTSIDE_OBSERVED_TAPE"
                dispositions[record["disposition"]] += 1
                records.append(record)
                continue

            prior_session = str(observed[prior_index])
            next_session = str(observed[next_index])
            record["prior_price_session"] = prior_session
            record["next_price_session"] = next_session
            if prior_session not in market_index or next_session not in market_index:
                raise RuntimeError("identity audit market-session index is incomplete")
            skipped = market_index[next_session] - market_index[prior_session] - 1
            if skipped < 0:
                raise RuntimeError("identity audit observed non-monotonic market sessions")
            record["skipped_market_sessions"] = int(skipped)

            exact = _between(exact_terminals.get(ticker, ()), prior_session, next_session)
            vendor = _between(vendor_terminals.get(ticker, ()), prior_session, next_session)
            evidence = [*(f"FROZEN:{x}" for x in exact), *(f"PIT_ACTION:{x}" for x in vendor)]
            record["terminal_evidence"] = ";".join(evidence)

            # Continuous adjacent-session price observations are stronger
            # security-continuity evidence than an isolated contradictory CIK
            # association. The CIK assertion is rejected as an identity boundary.
            if skipped == 0 and not exact:
                disposition = "CONTINUOUS_TAPE_CIK_REJECTED"
            elif exact or (skipped > 0 and vendor):
                disposition = "CORROBORATED_TERMINAL_BOUNDARY"
                episode_starts[ticker].add(next_session)
            elif skipped > 0:
                disposition = "UNRESOLVED_CIK_GAP_CONFLICT"
            else:
                disposition = "CONTINUOUS_TAPE_CIK_REJECTED"
            record["disposition"] = disposition
            dispositions[disposition] += 1
            records.append(record)
            if disposition == "UNRESOLVED_CIK_GAP_CONFLICT":
                blocking.append(dict(record))

    raw_changes = sum(len(rows) for rows in changes.values())
    summary = {
        "identity_authority": IDENTITY_AUTHORITY,
        "raw_cik_change_evidence_events": int(raw_changes),
        "cik_change_episode_boundaries": int(
            dispositions.get("CORROBORATED_TERMINAL_BOUNDARY", 0)
        ),
        "cik_changes_continuous_tape_rejected": int(
            dispositions.get("CONTINUOUS_TAPE_CIK_REJECTED", 0)
        ),
        "cik_changes_same_day_oscillation_rejected": int(
            dispositions.get("SAME_DAY_CIK_OSCILLATION_REJECTED", 0)
        ),
        "cik_changes_unresolved_gap_conflicts": int(
            dispositions.get("UNRESOLVED_CIK_GAP_CONFLICT", 0)
        ),
        "cik_changes_outside_observed_tape": int(
            dispositions.get("OUTSIDE_OBSERVED_TAPE", 0)
        ),
        "cik_changes_without_price_tape": int(
            dispositions.get("NO_PRICE_TAPE_FOR_TICKER", 0)
        ),
        "frozen_terminal_episode_boundaries": int(len(frozen_terminal_starts)),
        "blocking_identity_conflicts": int(len(blocking)),
        "blocking_identity_conflict_examples": blocking[:10],
        "first_listing_authority": "first observed historical SEP price session",
        "last_listing_authority": "causal terminal evidence only; no future last-price date is admitted",
        "permaticker_authority": "none",
        "related_tickers_authority": "none",
        "exchange_authority": "none/non-authoritative",
    }
    return episode_starts, records, blocking, summary


def audit_cik_identity_boundaries(
    *,
    sharadar_root: Path,
    cik_path: Path,
    start_year: int = 1997,
    end_year: int = 2026,
) -> tuple[list[dict], dict]:
    """Classify every CIK change against price continuity and terminal evidence."""
    price_dates = _price_dates(sharadar_root, start_year, end_year)
    _events, all_changes = _cik_changes(cik_path)
    changes = _changes_as_of(all_changes, f"{end_year:04d}-12-31")
    vendor, exact = _terminal_identity_evidence(sharadar_root)
    starts, records, _blocking, summary = _identity_boundary_classification(
        price_dates=price_dates,
        changes=changes,
        vendor_terminals=vendor,
        exact_terminals=exact,
    )
    summary = dict(summary)
    summary["tickers_with_price_tape"] = len(price_dates)
    summary["resulting_security_episodes"] = sum(len(rows) for rows in starts.values())
    summary["cik_change_records"] = len(records)
    return records, summary


def build_causal_metadata(
    *,
    sharadar_root: Path,
    cik_path: Path,
    SecurityMeta,
    start_year: int = 1997,
    end_year: int = 2026,
    fail_on_identity_conflict: bool = True,
):
    """Build SecurityMeta and resolver without current TICKERS authority."""
    price_dates = _price_dates(sharadar_root, start_year, end_year)
    cik_events, all_changes = _cik_changes(cik_path)
    changes = _changes_as_of(all_changes, f"{end_year:04d}-12-31")
    vendor_terminals, exact_terminals = _terminal_identity_evidence(sharadar_root)
    starts_by_ticker, _records, blocking, audit = _identity_boundary_classification(
        price_dates=price_dates,
        changes=changes,
        vendor_terminals=vendor_terminals,
        exact_terminals=exact_terminals,
    )
    if blocking and fail_on_identity_conflict:
        raise RuntimeError(
            "strict PIT identity authority found "
            f"{len(blocking)} uncorroborated CIK change(s) across price-tape gaps; "
            "identity cannot be certified; examples="
            + json.dumps(blocking[:5], sort_keys=True)
        )

    episodes: dict[str, list[IdentityEpisode]] = defaultdict(list)
    meta = {}
    canonical = {}

    for ticker, observed in sorted(price_dates.items()):
        if not observed:
            continue
        starts = sorted(starts_by_ticker.get(ticker, {observed[0]}))
        for episode, first in enumerate(starts):
            prior_rows = [(d, c) for d, c in cik_events.get(ticker, ()) if d < first]
            prior_cik = prior_rows[-1][1] if prior_rows else None
            sid = _sid(ticker, observed[0], episode)
            if sid in meta:
                raise RuntimeError(f"strict PIT synthetic security-id collision: {sid}")
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
    resolver = CausalIdentityResolver(episodes)
    sectors = {sid: None for sid in meta}
    audit = {
        **audit,
        "security_ids": len(meta),
        "tickers": len(episodes),
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
