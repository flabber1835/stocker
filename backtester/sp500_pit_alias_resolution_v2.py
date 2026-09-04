#!/usr/bin/env python3
"""Stage-3 S&P alias resolver using the exact Stage-2 output contract."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import defaultdict
from pathlib import Path

from backtester.sp500_pit_alias_resolution import (
    SCHEMA,
    _overlap,
    _sha256,
    _write_gzip_csv,
    build_discovery,
    load_tickers_zip,
)
from backtester.strict_pit_metadata import _price_dates, build_causal_metadata


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def resolve_aliases(*, identity_root: Path, tickers_zip: Path, sharadar_root: Path,
                    cik_path: Path, output: Path, start_year: int = 1997,
                    end_year: int = 2026) -> dict:
    summary = json.loads((identity_root / "identity-summary.json").read_text(encoding="utf-8"))
    work = _read_csv(identity_root / "sp500-identity-worklist.csv")
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
        for r in work
        if r.get("reason") in {"NO_CAUSAL_IDENTITY", "NO_CAUSAL_IDENTITY_DURING_MEMBERSHIP"}
    }
    resolved: list[dict[str, object]] = []
    ambiguous: list[dict[str, object]] = []
    no_candidate: list[dict[str, object]] = []

    for ticker, member_from, member_until in sorted(unresolved_keys):
        proposals = sorted(by_symbol.get(ticker, set()) - {ticker})
        candidates: list[dict[str, object]] = []
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
    _write_gzip_csv(output / "resolved-aliases.csv.gz",
                    ["sp500_ticker", "member_from", "member_until_exclusive", "resolved_ticker",
                     "security_id", "first_overlap_session", "last_overlap_session",
                     "candidate_source", "permaticker_groups"], resolved)
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
    summary_path = output / "alias-summary.json"
    summary_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    members = [output / "resolved-aliases.csv.gz", output / "ambiguous-aliases.csv.gz",
               output / "unresolved-aliases.csv.gz", summary_path]
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
