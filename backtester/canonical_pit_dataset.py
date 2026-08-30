#!/usr/bin/env python3
"""Build and validate one immutable PIT input dataset for both replay engines.

This module is dataset-maintenance code. Economic replay code may use
``CanonicalPITDataset`` to validate and read a finished artifact; it may not call
``build_dataset``.
"""
from __future__ import annotations

import argparse
import bisect
import csv
import gzip
import hashlib
import importlib.util
import io
import itertools
import json
import math
import os
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
import subprocess
import sys
from typing import Iterable, Iterator, Mapping, Sequence

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SHARED = ROOT / "shared"
for _path in (ROOT, SHARED):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from backtester.causal_split_overrides import (  # noqa: E402
    _expected_digest,
    _load_sidecar_records,
    install_primary_split_adjudication,
    sha256_file,
)
from backtester.historical_cash import complete_cash_factors  # noqa: E402
from backtester.causal_terminal_terms import (  # noqa: E402
    load_frozen_terminal_terms,
    merge_terminal_events,
)
from backtester.strict_pit_metadata import (  # noqa: E402
    CausalIssuerAuthority,
    SecurityTypeAuthority,
    build_causal_metadata,
)
from sentinel.core.terminal import (  # noqa: E402
    ActionSide,
    TERMINAL_ACTION_SIDES,
    TerminalCandidate,
    TerminalKind,
    TerminalTerms,
    coalesce_terminal_terms,
    terminal_from_action,
)
from sentinel.feed.actions_map import (  # noqa: E402
    dividends_from_actions,
    snap_to_session,
    split_rows_from_actions,
)
from sentinel.feed.domains import NormalisationReport, normalise_sep_rows  # noqa: E402
from stock_strategy_shared.split_reconciliation import SPLIT_UNRESOLVED  # noqa: E402


SCHEMA = "backtester.canonical-pit-dataset/1"
OBSERVATION_COLUMNS = (
    "session", "security_id", "ticker", "issuer_id", "issuer_source",
    "security_type", "security_type_source", "security_type_eligible",
    "sic", "ff12", "sector_source", "listing_active", "listing_first_session", "exchange",
    "exchange_authoritative", "raw_open", "raw_close", "signal_close",
    "reported_volume", "raw_compatible_volume", "split_ratio",
    "dividend_per_share", "tradeable", "metadata_admitted",
    "identity_source",
)
METADATA_COLUMNS = (
    "effective_session", "security_id", "ticker", "issuer_id",
    "issuer_source", "security_type", "security_type_source",
    "security_type_eligible", "sic", "ff12", "sector_source",
    "listing_first_session",
    "metadata_admitted",
)
ACTION_COLUMNS = (
    "effective_session", "security_id", "ticker", "action", "vendor_value",
    "canonical_value", "disposition", "sep_derived_value", "known_by",
    "authority", "evidence_hash",
)
TERMINAL_COLUMNS = (
    "effective_session", "security_id", "ticker", "kind", "disposition",
    "cash_per_share", "delivered_security_id", "delivered_ticker",
    "delivered_issuer_id", "exchange_ratio",
    "cash_in_lieu_price_per_delivered_share", "reference", "authority",
    "evidence_hash",
)
CASH_COLUMNS = (
    "session", "gap_factor", "intraday_factor", "close_to_close_factor",
    "source",
)
BENCHMARK_COLUMNS = ("session", "ticker", "close_to_close_factor", "level")
SESSION_HASH_COLUMNS = (
    "session", "observation_rows", "action_rows", "terminal_rows",
    "input_sha256",
)


@dataclass(frozen=True)
class _SecurityMeta:
    security_id: str
    ticker: str
    category: str | None = None
    permaticker: str | None = None
    related_tickers: tuple[str, ...] = ()
    first_session: str | None = None
    last_session: str | None = None
    exchange: str | None = None
    exchange_authoritative: bool = False


@dataclass(frozen=True)
class _IssuerMeta:
    issuer_id: str

    def issuer_key(self) -> tuple[str, str]:
        return self.issuer_id, "CANONICAL_PIT_DATASET"


def _sha256(path: Path) -> str:
    return sha256_file(path)


def _git_sha(root: Path) -> str | None:
    value = os.environ.get("BACKTESTER_BRANCH_SHA")
    if value:
        return value
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root, text=True
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _float_text(value) -> str:
    if value is None or pd.isna(value):
        return ""
    number = float(value)
    if not math.isfinite(number):
        return ""
    return format(number, ".17g")


def _text(value) -> str:
    return "" if value is None or pd.isna(value) else str(value)


class _DeterministicGzipCsv:
    def __init__(self, path: Path, columns: Sequence[str]):
        self.path = path
        self.columns = tuple(columns)
        self._raw = path.open("wb")
        self._gzip = gzip.GzipFile(
            filename="", mode="wb", fileobj=self._raw, compresslevel=6, mtime=0
        )
        self._text = io.TextIOWrapper(self._gzip, encoding="utf-8", newline="")
        self.writer = csv.DictWriter(
            self._text, fieldnames=self.columns, lineterminator="\n",
            extrasaction="raise",
        )
        self.writer.writeheader()
        self.rows = 0

    def write(self, row: Mapping[str, object]) -> str:
        normalized = {key: _text(row.get(key)) for key in self.columns}
        self.writer.writerow(normalized)
        self.rows += 1
        return json.dumps(normalized, sort_keys=True, separators=(",", ":"))

    def close(self) -> None:
        self._text.flush()
        self._text.detach()
        self._gzip.close()
        self._raw.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()


def _load_pit_model(cik_path: Path, sic_path: Path, sid_to_ticker: Mapping[str, str]):
    source = ROOT / "backtester/experiments/2026-08-27-sector-abc/run.py"
    spec = importlib.util.spec_from_file_location("canonical_pit_ff12_authority", source)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load PIT FF12 authority from {source}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.PITFF12(cik_path, sic_path, sid_to_ticker), module.ff12_for_sic


def _manifest_rows(path: Path) -> dict[str, dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return {row["file"]: row for row in csv.DictReader(handle)}


def _verify_manifest_member(path: Path, row: Mapping[str, str], label: str) -> dict:
    digest = _sha256(path)
    expected = str(row.get("sha256") or "")
    if digest != expected:
        raise RuntimeError(f"{label} hash mismatch: {digest} != {expected}")
    return {"sha256": digest, "bytes": path.stat().st_size}


def _verify_sha256sums(path: Path) -> dict[str, dict[str, object]]:
    verified: dict[str, dict[str, object]] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        digest, name = raw.split(maxsplit=1)
        member = path.parent / name.lstrip("*")
        observed = _sha256(member)
        if observed != digest:
            raise RuntimeError(f"{path}: {member.name} hash mismatch")
        verified[str(member)] = {"sha256": observed, "bytes": member.stat().st_size}
    return verified


def _record_identity_sep_sources(
    root: Path, start_year: int, end_year: int, source_inputs: dict[str, dict]
) -> None:
    sharadar_root = root / "sharadar"
    for year in range(start_year, end_year + 1):
        candidates = sorted(sharadar_root.glob(f"SHARADAR_SEP_{year}.csv*.gz"))
        if not candidates:
            continue
        digests = {path: _sha256(path) for path in candidates}
        if len(set(digests.values())) != 1:
            raise RuntimeError(f"non-identical raw SEP duplicates for {year}")
        path = candidates[0]
        source_inputs[str(path.relative_to(root))] = {
            "sha256": digests[path], "bytes": path.stat().st_size,
        }


def _session_axis(sfp_path: Path, start: str, end: str):
    frame = pd.read_csv(sfp_path, compression="gzip", low_memory=False)
    frame["date"] = frame["date"].astype(str).str[:10]
    frame = frame[(frame.date >= start) & (frame.date <= end)].copy()
    spy = frame[frame.ticker.astype(str).eq("SPY")].sort_values("date")
    bil = frame[frame.ticker.astype(str).eq("BIL")].sort_values("date")
    if spy.empty:
        raise RuntimeError("canonical dataset has no SPY session axis")
    sessions = spy.date.drop_duplicates().tolist()
    if sessions[0] != start or sessions[-1] != end:
        raise RuntimeError(
            f"SPY axis is {sessions[0]}..{sessions[-1]}, expected {start}..{end}"
        )
    bil_factors = {
        str(row.date): (
            float(row.prior_close_to_open_factor)
            if pd.notna(row.prior_close_to_open_factor) else 1.0,
            float(row.open_to_close_factor)
            if pd.notna(row.open_to_close_factor) else 1.0,
        )
        for row in bil.itertuples(index=False)
    }
    return sessions, spy, bil_factors


def _read_actions(path: Path) -> list[dict]:
    frame = pd.read_csv(path, compression="gzip", low_memory=False)
    rows = []
    for index, row in enumerate(frame.itertuples(index=False)):
        rows.append({
            "source_row_id": f"pit-actions-{index}",
            "date": str(row.date)[:10],
            "action": _text(row.action),
            "ticker": _text(row.ticker),
            "value": None if pd.isna(row.value) else float(row.value),
        })
    return rows


def _raw_sep_rows(
    sharadar_root: Path,
    start: str,
    end: str,
    source_inputs: dict[str, dict],
) -> Iterator[dict]:
    for year in range(int(start[:4]), int(end[:4]) + 1):
        candidates = sorted(sharadar_root.glob(f"SHARADAR_SEP_{year}.csv*.gz"))
        if not candidates:
            raise RuntimeError(f"missing raw SEP source for {year}")
        digests = {path: _sha256(path) for path in candidates}
        unique = set(digests.values())
        if len(unique) != 1:
            raise RuntimeError(
                f"non-identical raw SEP duplicates for {year}: "
                + ", ".join(f"{p.name}={d}" for p, d in digests.items())
            )
        path = candidates[0]
        source_inputs[str(path.relative_to(ROOT))] = {
            "sha256": digests[path], "bytes": path.stat().st_size,
        }
        columns = ["ticker", "date", "open", "close", "closeunadj", "volume"]
        frame = pd.read_csv(path, usecols=columns, low_memory=False)
        frame["ticker"] = frame.ticker.astype(str)
        frame["date"] = frame.date.astype(str).str[:10]
        frame = frame[(frame.date >= start) & (frame.date <= end)].copy()
        frame["_sequence"] = range(len(frame))
        frame.sort_values(["date", "ticker", "_sequence"], inplace=True, kind="mergesort")
        frame.drop_duplicates(["date", "ticker"], keep="last", inplace=True)
        frame.sort_values(["date", "ticker"], inplace=True, kind="mergesort")
        for row in frame.itertuples(index=False):
            yield {
                "ticker": row.ticker,
                "date": row.date,
                "open": row.open,
                "close": row.close,
                "closeunadj": row.closeunadj,
                "volume": row.volume,
            }


def _active_split_adjudications(
    data_path: Path, checksum_path: Path, start: str, end: str
) -> tuple[dict[tuple[str, str], dict], str, dict[tuple[str, str], str]]:
    expected = _expected_digest(checksum_path, data_path)
    observed = _sha256(data_path)
    if observed != expected:
        raise RuntimeError(f"split adjudication hash mismatch: {observed} != {expected}")
    payload = json.loads(data_path.read_text(encoding="utf-8"))
    records = list(payload.get("records") or [])
    sidecars, witnesses = _load_sidecar_records(data_path)
    records.extend(sidecars)
    active = {}
    evidence_hash = {}
    for row in records:
        key = (str(row["ticker"]), str(row["effective_session"]))
        if start <= key[1] <= end:
            if key in active:
                raise RuntimeError(f"duplicate split adjudication {key}")
            active[key] = dict(row)
    sidecar_by_event = {}
    for name, digest in witnesses:
        payload = json.loads((data_path.parent / f"{data_path.stem}.d" / name).read_text())
        row = payload["record"]
        sidecar_by_event[(str(row["ticker"]), str(row["effective_session"]))] = digest
    evidence_hash.update(sidecar_by_event)
    aggregate = hashlib.sha256(
        (observed + "\n" + "\n".join(f"{n}\0{d}" for n, d in witnesses)).encode()
    ).hexdigest()
    return active, aggregate, evidence_hash


def _metadata_record(
    model, issuer_authority, type_authority, sid, ticker, session,
    listing_first_session, ff12_for_sic,
):
    issuer_id, issuer_source = issuer_authority.issuer(sid, ticker, session)
    security_type, type_source = type_authority.classify(ticker, session)
    cik = issuer_authority.strict_prior_cik(ticker, session)
    sic = None
    if cik is not None:
        sic = model._strict_prior(
            model.sic_dates.get(cik, ()), model.sic_values.get(cik, ()), session
        )
    if sic is None:
        ff12 = f"UNKNOWN:{sid}"
        sector_source = "SEC_STRICT_PRIOR_SIC_UNKNOWN_SINGLETON"
    else:
        ff12 = ff12_for_sic(sic)
        sector_source = "SEC_CIK_SIC_STRICT_PRIOR_FROZEN_FF12"
    eligible = security_type == "common"
    return {
        "issuer_id": issuer_id,
        "issuer_source": issuer_source,
        "security_type": security_type,
        "security_type_source": type_source,
        "security_type_eligible": "1" if eligible else "0",
        "sic": "" if sic is None else str(int(sic)),
        "ff12": ff12,
        "sector_source": sector_source,
        "listing_first_session": str(listing_first_session),
        "metadata_admitted": "1" if eligible else "0",
    }


def _dataset_hash(members: Mapping[str, Mapping[str, object]]) -> str:
    digest = hashlib.sha256()
    for name in sorted(members):
        row = members[name]
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(row["sha256"]).encode("ascii"))
        digest.update(b"\0")
        digest.update(str(row["bytes"]).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def _canonical_terminal_rows(
    *,
    root: Path,
    sessions: Sequence[str],
    raw_actions: Sequence[dict],
    resolver,
    priced_tickers_by_session: Mapping[str, set[str]],
    issuer_authority: CausalIssuerAuthority,
) -> tuple[list[dict], str, int]:
    by_session: dict[str, list[dict]] = defaultdict(list)
    for raw in raw_actions:
        action = str(raw.get("action") or "").lower()
        if TERMINAL_ACTION_SIDES.get(action) is not ActionSide.TARGET:
            continue
        effective = snap_to_session(str(raw["date"]), sessions)
        if effective is not None:
            by_session[effective].append(raw)

    terms_path = root / "backtester/data/causal-terminal-terms-v1.json"
    terms_sums = root / "backtester/data/causal-terminal-terms-v1.SHA256"
    payload = json.loads(terms_path.read_text(encoding="utf-8"))
    terminal_meta: dict[str, _IssuerMeta] = {}
    for record in payload.get("records") or []:
        session = str(record.get("effective_session") or "")
        if not sessions or session < sessions[0] or session > sessions[-1]:
            continue
        delivered_ticker = record.get("delivered_ticker")
        if not delivered_ticker:
            continue
        delivered_sid = resolver.resolve(str(delivered_ticker), session)
        if delivered_sid is None:
            raise RuntimeError(
                f"terminal delivered identity unresolved: {delivered_ticker} {session}"
            )
        issuer_id, _source = issuer_authority.issuer(
            str(delivered_sid), str(delivered_ticker), session
        )
        terminal_meta[str(delivered_sid)] = _IssuerMeta(issuer_id)

    exact_by_session, terms_digest = load_frozen_terminal_terms(
        terms_path,
        terms_sums,
        sessions=sessions,
        resolve_identity=resolver.resolve,
        meta=terminal_meta,
        TerminalTerms=TerminalTerms,
        TerminalKind=TerminalKind,
        identity_binding="resolved",
    )
    result: list[dict] = []
    incomplete = 0
    for session in sessions:
        candidates = []
        ticker_by_sid: dict[str, str] = {}
        for raw in by_session.get(session, ()):
            ticker = str(raw.get("ticker") or "")
            if ticker.upper() not in priced_tickers_by_session.get(session, set()):
                continue
            sid = resolver.resolve(ticker, session)
            if sid is None:
                raise RuntimeError(
                    f"terminal identity unresolved for priced {ticker} on {session}"
                )
            terms = terminal_from_action(
                {**raw, "vendor_session": str(raw.get("date"))},
                session,
                security_id=str(sid),
            )
            if terms is None:
                raise RuntimeError(f"terminal action is not expressible: {ticker} {session}")
            ticker_by_sid[str(sid)] = ticker
            candidates.append(TerminalCandidate(
                terms=terms, source_key=str(raw["source_row_id"])
            ))
        vendor = []
        for outcome in coalesce_terminal_terms(candidates):
            if outcome.conflicting or outcome.selected is None:
                raise RuntimeError(f"conflicting terminal terms for {outcome.key}")
            vendor.append(outcome.selected.terms)
        merged = merge_terminal_events(session, vendor, exact_by_session.get(session, ()))
        exact_sids = {str(term.security_id) for term in exact_by_session.get(session, ())}
        for terms in merged:
            exact = str(terms.security_id) in exact_sids
            complete, reason = terms.completeness(1)
            if not complete:
                incomplete += 1
            ticker = ticker_by_sid.get(str(terms.security_id))
            if ticker is None:
                ticker = next(
                    str(row["ticker"]) for row in payload.get("records") or []
                    if str(row.get("effective_session")) == session
                    and resolver.resolve(str(row.get("ticker")), session)
                    == str(terms.security_id)
                )
            result.append({
                "effective_session": session,
                "security_id": str(terms.security_id),
                "ticker": ticker,
                "kind": terms.kind.value,
                "disposition": "EXACT_EVIDENCE" if exact else (
                    "PIT_ACTION_INCOMPLETE:" + reason if not complete else "PIT_ACTION_COMPLETE"
                ),
                "cash_per_share": _float_text(terms.cash_per_share),
                "delivered_security_id": _text(terms.delivered_security_id),
                "delivered_ticker": _text(terms.delivered_ticker),
                "delivered_issuer_id": _text(terms.delivered_issuer_id),
                "exchange_ratio": _float_text(terms.exchange_ratio),
                "cash_in_lieu_price_per_delivered_share": _float_text(
                    terms.cash_in_lieu_price_per_delivered_share
                ),
                "reference": terms.reference,
                "authority": "FROZEN_PRIMARY_TERMS" if exact else "PIT_ACTIONS",
                "evidence_hash": terms_digest if exact else "",
            })
    return sorted(
        result,
        key=lambda row: (
            row["effective_session"], row["security_id"], row["ticker"]
        ),
    ), terms_digest, incomplete


def _member(path: Path, root: Path, rows: int | None = None) -> dict:
    result = {"sha256": _sha256(path), "bytes": path.stat().st_size}
    if rows is not None:
        result["rows"] = int(rows)
    return result


def build_dataset(
    *,
    output: Path,
    start: str,
    measurement_start: str,
    end: str,
    root: Path = ROOT,
) -> dict:
    """Build a bounded canonical artifact from frozen raw authorities."""
    if not (start <= measurement_start <= end):
        raise ValueError("expected start <= measurement_start <= end")
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise RuntimeError(f"canonical dataset output is not empty: {output}")

    pit_root = root / "PIT input data"
    evidence_root = root / "research/sentinel-fastgate/pit-evidence"
    generated = evidence_root / "generated"
    phase1_manifest_path = pit_root / "MANIFEST.csv"
    price_manifest_path = pit_root / "PRICE_RECONSTRUCTION_MANIFEST.csv"
    phase1 = _manifest_rows(phase1_manifest_path)
    prices = _manifest_rows(price_manifest_path)
    source_inputs = {
        str(phase1_manifest_path.relative_to(root)): _member(phase1_manifest_path, root),
        str(price_manifest_path.relative_to(root)): _member(price_manifest_path, root),
    }

    actions_path = pit_root / "ACTIONS_PIT_ONLY.csv.gz"
    source_inputs[str(actions_path.relative_to(root))] = _verify_manifest_member(
        actions_path, phase1[actions_path.name], "PIT ACTIONS"
    )
    sfp_path = pit_root / "SFP_SPY_BIL_PRICE_FACTORS_PIT_ONLY.csv.gz"
    source_inputs[str(sfp_path.relative_to(root))] = _verify_manifest_member(
        sfp_path, prices[sfp_path.name], "PIT SFP factors"
    )
    cik_path = generated / "sec_cik_change_events.csv.gz"
    sic_path = generated / "sec_sic_submissions.csv.gz"
    positive_type = pit_root / "SEC_SECURITY_TYPE_POSITIVE_EVIDENCE.csv.gz"
    manual_type = pit_root / "SEC_SECURITY_TYPE_MANUAL_ADMISSION_AUDIT.csv"
    cash_authority = root / "backtester/data/GS3M_1996-12_2007-05.csv"
    for path in (cik_path, sic_path, positive_type, manual_type, cash_authority,
                 evidence_root / "ff12_sic_definition.txt"):
        source_inputs[str(path.relative_to(root))] = _member(path, root)
    for sums in (generated / "SHA256SUMS.txt", generated / "SEC_SIC_SHA256SUMS.txt"):
        source_inputs[str(sums.relative_to(root))] = _member(sums, root)
        for absolute, member in _verify_sha256sums(sums).items():
            member_path = Path(absolute)
            source_inputs[str(member_path.relative_to(root))] = member
    _record_identity_sep_sources(root, 1997, int(end[:4]), source_inputs)

    sessions, spy, bil_factors = _session_axis(sfp_path, start, end)
    session_set = set(sessions)
    action_rows = _read_actions(actions_path)
    replay_action_rows = [row for row in action_rows if str(row["date"]) >= start]
    splits, ambiguous_splits = split_rows_from_actions(replay_action_rows, sessions)
    if ambiguous_splits:
        raise RuntimeError(f"ambiguous split source rows: {ambiguous_splits[:5]}")
    dividends = dividends_from_actions(replay_action_rows, sessions)

    split_data = root / "backtester/data/causal-split-overrides-v1.json"
    split_sums = root / "backtester/data/causal-split-overrides-v1.SHA256"
    terminal_data = root / "backtester/data/causal-terminal-terms-v1.json"
    terminal_sums = root / "backtester/data/causal-terminal-terms-v1.SHA256"
    active_adjudications, adjudication_hash, evidence_hashes = _active_split_adjudications(
        split_data, split_sums, start, end
    )
    source_inputs[str(split_data.relative_to(root))] = _member(split_data, root)
    source_inputs[str(split_sums.relative_to(root))] = _member(split_sums, root)
    source_inputs[str(terminal_data.relative_to(root))] = _member(terminal_data, root)
    source_inputs[str(terminal_sums.relative_to(root))] = _member(terminal_sums, root)
    if active_adjudications:
        import stock_strategy_shared.split_reconciliation as split_module
        install_primary_split_adjudication(split_module, active_adjudications)

    meta, _sectors, resolver, canonical, identity_audit = build_causal_metadata(
        sharadar_root=root / "sharadar",
        cik_path=cik_path,
        SecurityMeta=_SecurityMeta,
        start_year=1997,
        end_year=int(end[:4]),
    )
    issuer_authority = CausalIssuerAuthority(cik_path)
    model, ff12_for_sic = _load_pit_model(cik_path, sic_path, canonical)
    type_authority = SecurityTypeAuthority(positive_type, manual_type, model)

    observation_paths = {
        year: output / f"observations-{year}.csv.gz"
        for year in range(int(start[:4]), int(end[:4]) + 1)
    }
    observation_writers = {
        year: _DeterministicGzipCsv(path, OBSERVATION_COLUMNS)
        for year, path in observation_paths.items()
    }
    metadata_path = output / "metadata-timeline.csv.gz"
    metadata_writer = _DeterministicGzipCsv(metadata_path, METADATA_COLUMNS)
    normalization = NormalisationReport()
    observed_security_ids: set[str] = set()
    last_metadata: dict[str, tuple] = {}
    observation_rows_by_session: dict[str, int] = defaultdict(int)
    priced_tickers_by_session: dict[str, set[str]] = defaultdict(set)
    session_parts: dict[str, list[str]] = defaultdict(list)
    dividend_by_event: dict[tuple[str, str], float] = {}
    raw_stream = _raw_sep_rows(root / "sharadar", start, end, source_inputs)

    try:
        for normalized in normalise_sep_rows(
            raw_stream,
            resolve_identity=lambda ticker, session: resolver.resolve(ticker, session),
            dividends=dividends,
            authoritative_splits=splits,
            report=normalization,
        ):
            bar = normalized.vendor
            session = str(bar.session)
            if session not in session_set:
                continue
            sid = str(bar.security_id)
            ticker = str(bar.ticker)
            metadata = _metadata_record(
                model, issuer_authority, type_authority, sid, ticker, session,
                meta[sid].first_session,
                ff12_for_sic,
            )
            row = {
                "session": session,
                "security_id": sid,
                "ticker": ticker,
                **metadata,
                "listing_active": "1",
                "exchange": "",
                "exchange_authoritative": "0",
                "raw_open": _float_text(bar.raw_open),
                "raw_close": _float_text(bar.raw_close),
                "signal_close": _float_text(normalized.close_signal),
                "reported_volume": _float_text(
                    None if bar.volume is None or normalized.close_signal is None
                    else float(bar.volume) * float(bar.raw_close) / float(normalized.close_signal)
                ),
                "raw_compatible_volume": _float_text(bar.volume),
                "split_ratio": _float_text(bar.split_ratio),
                "dividend_per_share": _float_text(bar.dividend_per_share),
                "tradeable": "1" if bar.tradeable else "0",
                "identity_source": "SEP_STRICT_PRIOR_CIK_EPISODE_V1",
            }
            year = int(session[:4])
            canonical_line = observation_writers[year].write(row)
            session_parts[session].append("O\0" + canonical_line)
            observation_rows_by_session[session] += 1
            observed_security_ids.add(sid)
            priced_tickers_by_session[session].add(ticker.upper())
            if float(bar.dividend_per_share or 0.0) != 0.0:
                dividend_by_event[(ticker, session)] = float(bar.dividend_per_share)

            metadata_tuple = tuple(metadata[column] for column in METADATA_COLUMNS[3:])
            if last_metadata.get(sid) != metadata_tuple:
                timeline_row = {
                    "effective_session": session,
                    "security_id": sid,
                    "ticker": ticker,
                    **metadata,
                }
                metadata_writer.write(timeline_row)
                last_metadata[sid] = metadata_tuple
    finally:
        for writer in observation_writers.values():
            writer.close()
        metadata_writer.close()

    unresolved = [
        {"ticker": ticker, "session": session, **value}
        for (ticker, session), value in sorted(normalization.split_dispositions.items())
        if value.get("disposition") == SPLIT_UNRESOLVED
    ]

    action_path = output / "actions.csv.gz"
    terminal_path = output / "terminal-events.csv.gz"
    action_count = 0
    action_rows_by_session: dict[str, int] = defaultdict(int)
    terminal_rows_by_session: dict[str, int] = defaultdict(int)
    canonical_actions = []
    for raw in replay_action_rows:
        effective = snap_to_session(str(raw["date"]), sessions)
        if effective is None or effective not in session_set:
            continue
        ticker = str(raw["ticker"])
        action = str(raw["action"]).lower()
        sid = resolver.resolve(ticker, effective)
        if sid is None:
            continue
        vendor = raw.get("value")
        canonical_value = vendor
        disposition = "PIT_ACTION_DIRECT"
        derived = None
        known_by = str(raw["date"])
        authority = "PIT_ACTIONS"
        evidence_hash = ""
        if action == "split":
            decision = normalization.split_dispositions.get((ticker, effective), {})
            canonical_value = decision.get("applied_ratio")
            disposition = str(decision.get("disposition") or "UNOBSERVED_SPLIT_DISPOSITION")
            derived = decision.get("derived")
            adjudication = active_adjudications.get((ticker, effective))
            if adjudication is not None:
                known_by = str(adjudication["known_by"])
                authority = "PRIMARY_SOURCE_ADJUDICATION"
                evidence_hash = evidence_hashes.get((ticker, effective), adjudication_hash)
        elif action in {"dividend", "spinoffdividend"}:
            canonical_value = dividend_by_event.get((ticker, effective), 0.0)
            disposition = "RAW_SHARE_DOMAIN_CONVERTED"
            authority = "PIT_ACTIONS_PLUS_SAME_SESSION_PRICE_DOMAIN"
        row = {
            "effective_session": effective,
            "security_id": sid,
            "ticker": ticker,
            "action": action,
            "vendor_value": _float_text(vendor),
            "canonical_value": _float_text(canonical_value),
            "disposition": disposition,
            "sep_derived_value": _float_text(derived),
            "known_by": known_by,
            "authority": authority,
            "evidence_hash": evidence_hash,
        }
        canonical_actions.append(row)
    canonical_actions.sort(key=lambda row: (
        row["effective_session"], row["security_id"], row["ticker"], row["action"]
    ))
    with _DeterministicGzipCsv(action_path, ACTION_COLUMNS) as action_writer:
        for row in canonical_actions:
            effective = str(row["effective_session"])
            canonical_line = action_writer.write(row)
            session_parts[effective].append("A\0" + canonical_line)
            action_rows_by_session[effective] += 1
            action_count += 1

    terminal_rows, terminal_terms_hash, incomplete_terminal_terms = \
        _canonical_terminal_rows(
            root=root,
            sessions=sessions,
            raw_actions=replay_action_rows,
            resolver=resolver,
            priced_tickers_by_session=priced_tickers_by_session,
            issuer_authority=issuer_authority,
        )
    with _DeterministicGzipCsv(terminal_path, TERMINAL_COLUMNS) as terminal_writer:
        for row in terminal_rows:
            effective = str(row["effective_session"])
            canonical_line = terminal_writer.write(row)
            session_parts[effective].append("T\0" + canonical_line)
            terminal_rows_by_session[effective] += 1
    terminal_count = len(terminal_rows)

    cash_path = output / "cash.csv.gz"
    benchmark_path = output / "benchmark.csv.gz"
    cash, cash_provenance = complete_cash_factors(sessions, bil_factors, cash_authority)
    with _DeterministicGzipCsv(cash_path, CASH_COLUMNS) as writer:
        for session in sessions:
            gap, intra = cash[session]
            source = "BIL" if session in bil_factors else "FRED_GS3M_STRICT_LAG"
            row = {
                "session": session,
                "gap_factor": _float_text(gap),
                "intraday_factor": _float_text(intra),
                "close_to_close_factor": _float_text(float(gap) * float(intra)),
                "source": source,
            }
            line = writer.write(row)
            session_parts[session].append("C\0" + line)

    spy_level = 1.0
    with _DeterministicGzipCsv(benchmark_path, BENCHMARK_COLUMNS) as writer:
        for index, row in enumerate(spy.itertuples(index=False)):
            factor = 1.0 if index == 0 or pd.isna(row.close_to_close_factor) \
                else float(row.close_to_close_factor)
            if index:
                spy_level *= factor
            item = {
                "session": str(row.date),
                "ticker": "SPY",
                "close_to_close_factor": _float_text(factor),
                "level": _float_text(spy_level),
            }
            line = writer.write(item)
            session_parts[str(row.date)].append("B\0" + line)

    session_hash_path = output / "session-hashes.csv"
    with session_hash_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SESSION_HASH_COLUMNS, lineterminator="\n")
        writer.writeheader()
        for session in sessions:
            digest = hashlib.sha256()
            for part in sorted(session_parts[session]):
                digest.update(part.encode("utf-8"))
                digest.update(b"\n")
            writer.writerow({
                "session": session,
                "observation_rows": observation_rows_by_session[session],
                "action_rows": action_rows_by_session[session],
                "terminal_rows": terminal_rows_by_session[session],
                "input_sha256": digest.hexdigest(),
            })

    members = {}
    for year, path in observation_paths.items():
        members[path.name] = _member(path, output, observation_writers[year].rows)
    members[metadata_path.name] = _member(metadata_path, output, metadata_writer.rows)
    members[action_path.name] = _member(action_path, output, action_count)
    members[terminal_path.name] = _member(terminal_path, output, terminal_count)
    members[cash_path.name] = _member(cash_path, output, len(sessions))
    members[benchmark_path.name] = _member(benchmark_path, output, len(sessions))
    members[session_hash_path.name] = _member(session_hash_path, output, len(sessions))
    dataset_hash = _dataset_hash(members)
    status = "PASS" if not unresolved else "FAIL"
    unknown_type = int(type_authority.unknown)
    unknown_issuer = sum(
        1 for sid, values in last_metadata.items()
        if values[0].startswith("SEC_UNKNOWN:")
    )
    manifest = {
        "schema": SCHEMA,
        "dataset_id": f"strict-pit-{start}-{end}-{dataset_hash[:16]}",
        "status": status,
        "dataset_hash": dataset_hash,
        "reconstruction_code_sha": _git_sha(root),
        "reconstruction_module_sha256": _sha256(Path(__file__)),
        "window": {
            "warmup_start": start,
            "measurement_start": measurement_start,
            "end": end,
        },
        "counts": {
            "observation_rows": sum(writer.rows for writer in observation_writers.values()),
            "security_count": len(observed_security_ids),
            "session_count": len(sessions),
            "metadata_timeline_rows": metadata_writer.rows,
            "action_rows": action_count,
            "terminal_rows": terminal_count,
            "incomplete_terminal_terms": incomplete_terminal_terms,
            "unresolved_corporate_actions": len(unresolved),
            "unknown_security_type_observations": unknown_type,
            "unknown_issuer_securities_at_end": unknown_issuer,
        },
        "blockers": {"unresolved_corporate_actions": unresolved},
        "identity_audit": identity_audit,
        "security_type_audit": type_authority.audit(),
        "cash_provenance": cash_provenance,
        "adjudication_hash": adjudication_hash,
        "terminal_terms_hash": terminal_terms_hash,
        "source_files": dict(sorted(source_inputs.items())),
        "members": dict(sorted(members.items())),
        "field_authorities": {
            "identity": "historical SEP plus strict-prior SEC CIK-change episode boundary",
            "issuer": "strict-prior SEC CIK; unknown security singleton",
            "security_type": "strict-prior positive SEC/EDGAR evidence; unknown ineligible",
            "sector": "strict-prior SEC CIK -> strict-prior SIC -> frozen FF12",
            "listing": "observed historical SEP tape",
            "exchange": "non-authoritative and economically inert",
            "prices_volume": "shared production Sharadar domain normalizer",
            "corporate_actions": "PIT ACTIONS plus SEP witness and frozen adjudications",
            "cash": "BIL when available; previous completed month GS3M otherwise",
        },
    }
    manifest_path = output / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    sums_path = output / "SHA256SUMS.txt"
    sum_members = {**members, manifest_path.name: _member(manifest_path, output)}
    sums_path.write_text(
        "".join(f"{row['sha256']}  {name}\n" for name, row in sorted(sum_members.items())),
        encoding="utf-8",
    )
    return manifest


class CanonicalPITDataset:
    """Hash-validating read-only view of a completed canonical artifact."""

    def __init__(
        self,
        root: Path,
        *,
        expected_start: str | None = None,
        expected_end: str | None = None,
        require_pass: bool = True,
    ):
        self.root = Path(root)
        self.manifest_path = self.root / "manifest.json"
        self.manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        if self.manifest.get("schema") != SCHEMA:
            raise RuntimeError(f"unexpected canonical PIT schema: {self.manifest.get('schema')!r}")
        if require_pass and self.manifest.get("status") != "PASS":
            raise RuntimeError(
                "canonical PIT dataset is not certified: "
                + json.dumps(self.manifest.get("blockers") or {}, sort_keys=True)
            )
        window = self.manifest.get("window") or {}
        if expected_start is not None and window.get("warmup_start") != expected_start:
            raise RuntimeError("canonical PIT warmup start mismatch")
        if expected_end is not None and window.get("end") != expected_end:
            raise RuntimeError("canonical PIT end mismatch")
        observed_members = {}
        for name, expected in (self.manifest.get("members") or {}).items():
            path = self.root / name
            if not path.is_file():
                raise RuntimeError(f"canonical PIT member missing: {name}")
            observed = _member(path, self.root, expected.get("rows"))
            if (observed["sha256"] != expected.get("sha256")
                    or observed["bytes"] != int(expected.get("bytes"))):
                raise RuntimeError(f"canonical PIT member changed: {name}")
            observed_members[name] = expected
        observed_hash = _dataset_hash(observed_members)
        if observed_hash != self.manifest.get("dataset_hash"):
            raise RuntimeError(
                f"canonical PIT aggregate hash mismatch: {observed_hash} != "
                f"{self.manifest.get('dataset_hash')}"
            )
        if int((self.manifest.get("counts") or {}).get("unresolved_corporate_actions", -1)) != 0 \
                and require_pass:
            raise RuntimeError("canonical PIT dataset retains unresolved corporate actions")
        self.dataset_hash = observed_hash
        self.window = window
        hashes = pd.read_csv(self.root / "session-hashes.csv", dtype=str)
        self.session_hashes = dict(zip(hashes.session, hashes.input_sha256))
        self.sessions = tuple(hashes.session.astype(str))
        timeline = pd.read_csv(
            self.root / "metadata-timeline.csv.gz", compression="gzip", dtype=str,
            keep_default_na=False,
        )
        self._timeline_rows: dict[str, list[dict[str, str]]] = defaultdict(list)
        self._timeline_dates: dict[str, list[str]] = defaultdict(list)
        for row in timeline.to_dict("records"):
            sid = str(row["security_id"])
            self._timeline_rows[sid].append(row)
            self._timeline_dates[sid].append(str(row["effective_session"]))
        self._first_session = {
            sid: rows[0]["effective_session"]
            for sid, rows in self._timeline_rows.items()
        }

    def metadata_for(self, security_id: str, session: str) -> dict[str, str] | None:
        sid = str(security_id)
        index = bisect.bisect_right(self._timeline_dates.get(sid, ()), str(session)) - 1
        return None if index < 0 else self._timeline_rows[sid][index]

    def observation_path(self, year: int) -> Path:
        path = self.root / f"observations-{int(year)}.csv.gz"
        if not path.is_file():
            raise RuntimeError(f"canonical PIT observation partition missing: {path.name}")
        return path

    def observations(self, year: int) -> pd.DataFrame:
        return pd.read_csv(
            self.observation_path(year), compression="gzip", dtype={
                "security_id": str, "ticker": str, "session": str,
            }, low_memory=False,
        )

    def research_observations(self, year: int) -> pd.DataFrame:
        frame = self.observations(year)
        return frame.rename(columns={
            "session": "date",
            "signal_close": "close",
            "raw_close": "closeunadj",
            "raw_open": "canonical_raw_open",
            "reported_volume": "volume",
        })

    def normalised_rows(self):
        from sentinel.feed.domains import NormalisedBar
        from stock_strategy_shared.wealth_core.feed import VendorBar

        for year in range(
            int(self.window["warmup_start"][:4]), int(self.window["end"][:4]) + 1
        ):
            for row in self.observations(year).itertuples(index=False):
                yield NormalisedBar(
                    vendor=VendorBar(
                        session=str(row.session),
                        security_id=str(row.security_id),
                        ticker=str(row.ticker),
                        raw_close=float(row.raw_close),
                        raw_open=float(row.raw_open),
                        volume=(
                            None if pd.isna(row.raw_compatible_volume)
                            else float(row.raw_compatible_volume)
                        ),
                        split_ratio=float(row.split_ratio),
                        dividend_per_share=float(row.dividend_per_share),
                        tradeable=str(row.tradeable) in {"1", "1.0", "True", "true"},
                    ),
                    close_signal=float(row.signal_close),
                )

    def cash_factors(self) -> dict[str, tuple[float, float]]:
        frame = pd.read_csv(self.root / "cash.csv.gz", compression="gzip")
        return {
            str(row.session): (float(row.gap_factor), float(row.intraday_factor))
            for row in frame.itertuples(index=False)
        }

    def benchmark(self) -> tuple[dict[str, float], dict[str, float]]:
        frame = pd.read_csv(self.root / "benchmark.csv.gz", compression="gzip")
        levels = {str(row.session): float(row.level) for row in frame.itertuples(index=False)}
        returns = {
            str(row.session): float(row.close_to_close_factor) - 1.0
            for row in frame.itertuples(index=False)
        }
        return levels, returns

    def base_metadata(self, SecurityMeta) -> tuple[dict, dict, object, dict[str, str]]:
        meta = {}
        sectors = {}
        sid_to_ticker = {}
        for sid, rows in self._timeline_rows.items():
            first = rows[0]
            ticker = str(first["ticker"])
            meta[sid] = SecurityMeta(
                security_id=sid,
                ticker=ticker,
                category=None,
                permaticker=None,
                related_tickers=(),
                first_session=str(first["listing_first_session"]),
                last_session=None,
                exchange=None,
                exchange_authoritative=False,
            )
            sectors[sid] = None
            sid_to_ticker[sid] = ticker

        class Resolver:
            def __init__(self, dataset):
                self.dataset = dataset

            def resolve(self, ticker, session):
                matches = [
                    sid for sid, rows in self.dataset._timeline_rows.items()
                    if rows[0]["ticker"] == str(ticker)
                    and rows[0]["effective_session"] <= str(session)
                ]
                if not matches:
                    return None
                active = [
                    sid for sid in matches
                    if self.dataset.metadata_for(sid, str(session)) is not None
                ]
                return sorted(active or matches)[-1]

        return meta, sectors, Resolver(self), sid_to_ticker

    def terminal_terms(self) -> dict[str, tuple[object, ...]]:
        from stock_strategy_shared.wealth_core.terminal import TerminalKind, TerminalTerms

        frame = pd.read_csv(
            self.root / "terminal-events.csv.gz", compression="gzip",
            dtype=str, keep_default_na=False,
        )
        by_session: dict[str, list[object]] = defaultdict(list)
        floats = (
            "cash_per_share", "exchange_ratio",
            "cash_in_lieu_price_per_delivered_share",
        )
        for row in frame.to_dict("records"):
            kwargs = {
                "session": row["effective_session"],
                "security_id": row["security_id"],
                "kind": TerminalKind(row["kind"]),
                "reference": row["reference"],
                "delivered_security_id": row["delivered_security_id"] or None,
                "delivered_ticker": row["delivered_ticker"] or None,
                "delivered_issuer_id": row["delivered_issuer_id"] or None,
            }
            for field in floats:
                kwargs[field] = None if not row[field] else float(row[field])
            by_session[row["effective_session"]].append(TerminalTerms(**kwargs))
        return {
            session: tuple(sorted(rows, key=lambda term: term.security_id))
            for session, rows in sorted(by_session.items())
        }

    def group(self, sid: str, session: str, ticker: str | None = None) -> str:
        row = self.metadata_for(str(sid), str(session))
        return f"UNKNOWN:{sid}" if row is None else str(row["ff12"])

    def session_hash(self, session: str) -> str:
        try:
            return self.session_hashes[str(session)]
        except KeyError as exc:
            raise RuntimeError(f"canonical PIT session hash missing for {session}") from exc


def _main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build")
    build.add_argument("--output", type=Path, required=True)
    build.add_argument("--warmup-start", default="2006-01-03")
    build.add_argument("--measurement-start", default="2006-07-31")
    build.add_argument("--end", default="2007-12-31")
    validate = sub.add_parser("validate")
    validate.add_argument("--dataset", type=Path, required=True)
    validate.add_argument("--allow-failed", action="store_true")
    args = parser.parse_args()
    if args.command == "build":
        manifest = build_dataset(
            output=args.output,
            start=args.warmup_start,
            measurement_start=args.measurement_start,
            end=args.end,
        )
        print(json.dumps({
            "status": manifest["status"],
            "dataset_id": manifest["dataset_id"],
            "dataset_hash": manifest["dataset_hash"],
            "counts": manifest["counts"],
            "blockers": manifest["blockers"],
        }, indent=2, sort_keys=True))
        return 0 if manifest["status"] == "PASS" else 2
    dataset = CanonicalPITDataset(args.dataset, require_pass=not args.allow_failed)
    print(json.dumps({
        "status": dataset.manifest["status"],
        "dataset_id": dataset.manifest["dataset_id"],
        "dataset_hash": dataset.dataset_hash,
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
