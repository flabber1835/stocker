#!/usr/bin/env python3
"""Resolve S&P 500 historical ticker aliases against the causal SEP identity domain.

Sharadar TICKERS metadata is discovery-only. A mapping is admitted only when exactly
one proposed ticker has an actual SEP price-tape episode overlapping the S&P
membership interval. This prevents current metadata, stale aliases, and reused
symbols from creating economic history.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Iterable, Mapping, Sequence

import pandas as pd

from backtester.strict_pit_metadata import _price_dates, build_causal_metadata

SCHEMA = "backtester.sp500-pit-alias-resolution/1"


def _norm(value: object) -> str:
    return str(value or "").strip().upper()


def _split_symbols(value: object) -> set[str]:
    text = str(value or "").upper()
    for token in "|;/":
        text = text.replace(token, ",")
    return {x.strip() for x in text.split(",") if x.strip()}


def _read_gzip_csv(path: Path) -> list[dict[str, str]]:
    with gzip.open(path, "rt", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def _write_gzip_csv(path: Path, fields: Sequence[str], rows: Iterable[Mapping[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, compresslevel=9, mtime=0) as gz:
            with io.TextIOWrapper(gz, encoding="utf-8", newline="") as text:
                writer = csv.DictWriter(text, fieldnames=list(fields), lineterminator="\n", extrasaction="ignore")
                writer.writeheader()
                for row in rows:
                    writer.writerow({k: row.get(k, "") for k in fields})


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_tickers_zip(path: Path) -> tuple[list[dict[str, str]], str]:
    with zipfile.ZipFile(path) as zf:
        members = [n for n in zf.namelist() if n.lower().endswith(".csv")]
        if not members:
            raise RuntimeError("SHARADAR_TICKERS.zip contains no CSV")
        # Prefer the canonical Sharadar TICKERS export if multiple CSVs exist.
        member = sorted(members, key=lambda n: ("ticker" not in n.lower(), len(n), n))[0]
        data = zf.read(member)
    text = io.TextIOWrapper(io.BytesIO(data), encoding="utf-8-sig", errors="strict", newline="")
    rows = list(csv.DictReader(text))
    if not rows:
        raise RuntimeError("empty TICKERS CSV")
    required_any = {"ticker", "permaticker", "relatedtickers"}
    lower = {str(x).lower() for x in rows[0]}
    if "ticker" not in lower:
        raise RuntimeError(f"TICKERS CSV missing ticker column: {sorted(lower)}")
    return rows, member


def _field(row: Mapping[str, str], *names: str) -> str:
    by_lower = {str(k).lower(): v for k, v in row.items()}
    for name in names:
        if name.lower() in by_lower:
            return str(by_lower[name.lower()] or "")
    return ""


def build_discovery(rows: Sequence[Mapping[str, str]]) -> tuple[dict[str, set[str]], dict[str, set[str]], dict[str, set[str]]]:
    by_symbol: dict[str, set[str]] = defaultdict(set)
    by_permaticker: dict[str, set[str]] = defaultdict(set)
    permatickers_for_symbol: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        ticker = _norm(_field(row, "ticker"))
        permaticker = str(_field(row, "permaticker")).strip()
        related = _split_symbols(_field(row, "relatedtickers", "related_tickers"))
        symbols = ({ticker} if ticker else set()) | related
        if ticker:
            by_symbol[ticker].add(ticker)
        for symbol in symbols:
            if ticker:
                by_symbol[symbol].add(ticker)
            if permaticker:
                permatickers_for_symbol[symbol].add(permaticker)
        if permaticker and ticker:
            by_permaticker[permaticker].add(ticker)
    # Expand symbol candidates through the permanent-security grouping.
    for symbol, perms in list(permatickers_for_symbol.items()):
        for perm in perms:
            by_symbol[symbol].update(by_permaticker.get(perm, ()))
    return by_symbol, by_permaticker, permatickers_for_symbol


def _overlap(member_from: str, member_until: str, price_sessions: Sequence[str]) -> tuple[str, str] | None:
    if not price_sessions:
        return None
    left = max(member_from, price_sessions[0])
    right_bound = member_until or "9999-12-31"
    right = min(right_bound, price_sessions[-1])
    # membership uses [from, until); tape observations are inclusive sessions
    if left >= right_bound or left > price_sessions[-1] or price_sessions[0] >= right_bound:
        return None
    relevant = [d for d in price_sessions if d >= member_from and d < right_bound]
    if not relevant:
        return None
    return relevant[0], relevant[-1]


def resolve_aliases(*, identity_root: Path, tickers_zip: Path, sharadar_root: Path, cik_path: Path,
                    output: Path, start_year: int = 1997, end_year: int = 2026) -> dict:
    summary = json.loads((identity_root / "identity-summary.json").read_text(encoding="utf-8"))
    work = _read_gzip_csv(identity_root / "sp500-identity-worklist.csv.gz")
    membership_rows = _read_gzip_csv(identity_root / "sp500-membership-identity.csv.gz")
    tickers_rows, tickers_member = load_tickers_zip(tickers_zip)
    by_symbol, _by_perm, perms_for_symbol = build_discovery(tickers_rows)
    price_dates = _price_dates(sharadar_root, start_year, end_year)

    class SecurityMeta:
        def __init__(self, security_id, ticker, category, permaticker, related_tickers,
                     first_session, last_session, exchange, exchange_authoritative):
            self.security_id = security_id
            self.ticker = ticker
            self.first_session = first_session

    _meta, _sectors, resolver, _canonical, audit = build_causal_metadata(
        sharadar_root=sharadar_root,
        cik_path=cik_path,
        SecurityMeta=SecurityMeta,
        start_year=start_year,
        end_year=end_year,
        fail_on_identity_conflict=True,
    )

    unresolved_keys = {
        (r["ticker"], r["member_from"], r.get("member_until_exclusive", ""))
        for r in work if r.get("reason") not in {"PREFIX_BEFORE_LOCAL_TAPE"}
    }
    resolved: list[dict[str, object]] = []
    ambiguous: list[dict[str, object]] = []
    no_candidate: list[dict[str, object]] = []

    for ticker, member_from, member_until in sorted(unresolved_keys):
        proposals = sorted(by_symbol.get(ticker, set()) - {ticker})
        candidates = []
        for candidate in proposals:
            overlap = _overlap(member_from, member_until, price_dates.get(candidate, ()))
            if overlap is None:
                continue
            sid = resolver.resolve(candidate, overlap[0])
            if sid is None:
                continue
            candidates.append({
                "sp500_ticker": ticker,
                "member_from": member_from,
                "member_until_exclusive": member_until,
                "resolved_ticker": candidate,
                "security_id": sid,
                "first_overlap_session": overlap[0],
                "last_overlap_session": overlap[1],
                "candidate_source": "SHARADAR_TICKERS_DISCOVERY_PLUS_SEP_OVERLAP",
                "permaticker_groups": ";".join(sorted(perms_for_symbol.get(ticker, ()))),
            })
        # Deduplicate by actual security identity. Multiple aliases pointing to the same
        # security episode are one admissible candidate.
        by_sid: dict[str, dict[str, object]] = {}
        for row in candidates:
            sid = str(row["security_id"])
            prior = by_sid.get(sid)
            if prior is None or str(row["resolved_ticker"]) < str(prior["resolved_ticker"]):
                by_sid[sid] = row
        candidates = list(by_sid.values())
        if len(candidates) == 1:
            resolved.append(candidates[0])
        elif len(candidates) > 1:
            ambiguous.append({
                "sp500_ticker": ticker,
                "member_from": member_from,
                "member_until_exclusive": member_until,
                "candidate_count": len(candidates),
                "candidates": ";".join(
                    f"{x['resolved_ticker']}:{x['security_id']}:{x['first_overlap_session']}:{x['last_overlap_session']}"
                    for x in sorted(candidates, key=lambda x: (str(x['resolved_ticker']), str(x['security_id'])))
                ),
            })
        else:
            no_candidate.append({
                "sp500_ticker": ticker,
                "member_from": member_from,
                "member_until_exclusive": member_until,
                "proposed_aliases": ";".join(proposals),
                "permaticker_groups": ";".join(sorted(perms_for_symbol.get(ticker, ()))),
            })

    output.mkdir(parents=True, exist_ok=True)
    resolved_fields = ["sp500_ticker", "member_from", "member_until_exclusive", "resolved_ticker",
                       "security_id", "first_overlap_session", "last_overlap_session",
                       "candidate_source", "permaticker_groups"]
    _write_gzip_csv(output / "resolved-aliases.csv.gz", resolved_fields, resolved)
    _write_gzip_csv(output / "ambiguous-aliases.csv.gz",
                    ["sp500_ticker", "member_from", "member_until_exclusive", "candidate_count", "candidates"], ambiguous)
    _write_gzip_csv(output / "unresolved-aliases.csv.gz",
                    ["sp500_ticker", "member_from", "member_until_exclusive", "proposed_aliases", "permaticker_groups"], no_candidate)

    result = {
        "schema": SCHEMA,
        "status": "ALIAS_DIAGNOSTIC_COMPLETE",
        "membership_dataset_hash": summary["membership_dataset_hash"],
        "input_unresolved_intervals": len(unresolved_keys),
        "resolved_intervals": len(resolved),
        "ambiguous_intervals": len(ambiguous),
        "still_unresolved_intervals": len(no_candidate),
        "tickers_metadata_rows": len(tickers_rows),
        "tickers_zip_member": tickers_member,
        "blocking_identity_conflicts": int(audit.get("blocking_identity_conflicts", 0)),
        "authority": "TICKERS metadata discovery only; admission requires unique causal SEP episode overlap",
    }
    (output / "alias-summary.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    members = [output / "resolved-aliases.csv.gz", output / "ambiguous-aliases.csv.gz",
               output / "unresolved-aliases.csv.gz", output / "alias-summary.json"]
    (output / "SHA256SUMS.txt").write_text(
        "".join(f"{_sha256(p)}  {p.name}\n" for p in sorted(members)), encoding="utf-8"
    )
    return result


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--identity-root", type=Path, required=True)
    p.add_argument("--tickers-zip", type=Path, required=True)
    p.add_argument("--sharadar-root", type=Path, required=True)
    p.add_argument("--cik-path", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--start-year", type=int, default=1997)
    p.add_argument("--end-year", type=int, default=2026)
    args = p.parse_args()
    print(json.dumps(resolve_aliases(**vars(args)), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
