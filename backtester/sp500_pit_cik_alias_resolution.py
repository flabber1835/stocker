#!/usr/bin/env python3
"""Discover historical S&P ticker aliases through SEC issuer-CIK linkage.

This is an identity-reconstruction diagnostic. SEC CIK supplies issuer linkage;
actual Sharadar SEP observations supply the candidate security/ticker existence.
No candidate is admitted merely because a CIK or current vendor record matches.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Iterable, Mapping, Sequence

import pandas as pd

from backtester.strict_pit_metadata import _price_dates, build_causal_metadata

SCHEMA = "backtester.sp500-pit-cik-alias-diagnostic/1"


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def _write_csv(path: Path, fields: Sequence[str], rows: Iterable[Mapping[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(fields), lineterminator="\n", extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow({k: row.get(k, "") for k in fields})


def _sha256(path: Path) -> str:
    h=hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024*1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _norm_cik(v: object) -> str:
    text=str(v or "").strip()
    try:
        return str(int(float(text))) if text else ""
    except (TypeError, ValueError, OverflowError):
        return ""


def _parse_gaps(text: str) -> list[tuple[str,str]]:
    out=[]
    for part in str(text or "").split(";"):
        if ".." not in part:
            continue
        a,b=part.split("..",1)
        if a and b and a < b:
            out.append((a,b))
    return out


def _overlap_sessions(sessions: Sequence[str], start: str, end: str) -> tuple[str,str] | None:
    xs=[x for x in sessions if start <= x < end]
    return (xs[0],xs[-1]) if xs else None


def discover(*, coverage_root: Path, sharadar_root: Path, cik_path: Path,
             output: Path, start_year: int=1997, end_year: int=2026) -> dict:
    gaps=_read_csv(coverage_root / "coverage-worklist.csv")
    frame=pd.read_csv(cik_path, compression="gzip", usecols=["filing_date","ticker","issuer_cik"], low_memory=False)
    frame=frame.dropna(subset=["ticker","issuer_cik"])
    frame["ticker"]=frame["ticker"].astype(str).str.strip().str.upper()
    frame["issuer_cik"]=frame["issuer_cik"].map(_norm_cik)
    frame=frame[frame["issuer_cik"]!=""]
    ciks_by_ticker: dict[str,set[str]]=defaultdict(set)
    tickers_by_cik: dict[str,set[str]]=defaultdict(set)
    for row in frame.itertuples(index=False):
        ticker=str(row.ticker); cik=str(row.issuer_cik)
        ciks_by_ticker[ticker].add(cik); tickers_by_cik[cik].add(ticker)

    price_dates=_price_dates(sharadar_root,start_year,end_year)

    class SecurityMeta:
        def __init__(self, security_id, ticker, category, permaticker, related_tickers,
                     first_session, last_session, exchange, exchange_authoritative):
            self.security_id=security_id; self.ticker=ticker; self.first_session=first_session
    _meta,_sectors,resolver,_canonical,audit=build_causal_metadata(
        sharadar_root=sharadar_root,cik_path=cik_path,SecurityMeta=SecurityMeta,
        start_year=start_year,end_year=end_year,fail_on_identity_conflict=True)

    candidates=[]; no_cik=[]; ambiguous=[]; unique=[]
    for row in gaps:
        source=str(row["ticker"]).upper()
        source_ciks=sorted(ciks_by_ticker.get(source,()))
        for gs,ge in _parse_gaps(row.get("gap_ranges","")):
            if not source_ciks:
                no_cik.append({"ticker":source,"gap_from":gs,"gap_until_exclusive":ge,"reason":"NO_SEC_CIK_FOR_SOURCE_SYMBOL"})
                continue
            hits=[]
            for cik in source_ciks:
                for candidate in sorted(tickers_by_cik.get(cik,())):
                    if candidate==source:
                        continue
                    overlap=_overlap_sessions(price_dates.get(candidate,()),gs,ge)
                    if not overlap:
                        continue
                    sid=resolver.resolve(candidate,overlap[0])
                    if sid is None:
                        continue
                    hits.append({
                        "ticker":source,"gap_from":gs,"gap_until_exclusive":ge,
                        "issuer_cik":cik,"candidate_ticker":candidate,"security_id":sid,
                        "first_overlap_session":overlap[0],"last_overlap_session":overlap[1],
                        "authority":"SEC_CIK_ISSUER_LINK_DISCOVERY_PLUS_CAUSAL_SEP_OVERLAP",
                    })
            dedup={}
            for hit in hits:
                key=(str(hit["security_id"]),str(hit["first_overlap_session"]),str(hit["last_overlap_session"]))
                dedup.setdefault(key,hit)
            hits=list(dedup.values())
            candidates.extend(hits)
            if len(hits)==1:
                unique.append(hits[0])
            elif len(hits)>1:
                ambiguous.append({
                    "ticker":source,"gap_from":gs,"gap_until_exclusive":ge,
                    "candidate_count":len(hits),
                    "candidates":";".join(
                        f"{h['candidate_ticker']}:{h['issuer_cik']}:{h['security_id']}:{h['first_overlap_session']}:{h['last_overlap_session']}"
                        for h in sorted(hits,key=lambda h:(h['candidate_ticker'],h['security_id']))
                    ),
                })
            else:
                no_cik.append({
                    "ticker":source,"gap_from":gs,"gap_until_exclusive":ge,
                    "reason":"CIK_PRESENT_BUT_NO_SEP_ALIAS_OVERLAP",
                    "issuer_ciks":";".join(source_ciks),
                })

    output.mkdir(parents=True,exist_ok=True)
    _write_csv(output/"unique-cik-aliases.csv",[
        "ticker","gap_from","gap_until_exclusive","issuer_cik","candidate_ticker","security_id",
        "first_overlap_session","last_overlap_session","authority"],unique)
    _write_csv(output/"ambiguous-cik-aliases.csv",[
        "ticker","gap_from","gap_until_exclusive","candidate_count","candidates"],ambiguous)
    _write_csv(output/"unresolved-cik-aliases.csv",[
        "ticker","gap_from","gap_until_exclusive","reason","issuer_ciks"],no_cik)
    result={
        "schema":SCHEMA,"status":"CIK_ALIAS_DIAGNOSTIC_COMPLETE",
        "coverage_gap_intervals":len(gaps),
        "gap_ranges_examined":sum(len(_parse_gaps(r.get("gap_ranges",""))) for r in gaps),
        "unique_gap_aliases":len(unique),"ambiguous_gap_aliases":len(ambiguous),
        "unresolved_gap_aliases":len(no_cik),"blocking_identity_conflicts":int(audit.get("blocking_identity_conflicts",0)),
        "sec_source_tickers":len(ciks_by_ticker),"sec_issuer_ciks":len(tickers_by_cik),
    }
    s=output/"cik-alias-summary.json"; s.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    members=[s,output/"unique-cik-aliases.csv",output/"ambiguous-cik-aliases.csv",output/"unresolved-cik-aliases.csv"]
    (output/"SHA256SUMS.txt").write_text("".join(f"{_sha256(p)}  {p.name}\n" for p in sorted(members)),encoding="utf-8")
    return result


def main()->int:
    p=argparse.ArgumentParser(); p.add_argument("--coverage-root",type=Path,required=True); p.add_argument("--sharadar-root",type=Path,required=True); p.add_argument("--cik-path",type=Path,required=True); p.add_argument("--output",type=Path,required=True); p.add_argument("--start-year",type=int,default=1997); p.add_argument("--end-year",type=int,default=2026)
    args=p.parse_args(); print(json.dumps(discover(**vars(args)),indent=2,sort_keys=True)); return 0
if __name__=="__main__": raise SystemExit(main())
