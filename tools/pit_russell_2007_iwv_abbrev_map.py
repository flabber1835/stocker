#!/usr/bin/env python3
"""Second-pass 2007 IWV identity mapper using documented Russell label abbreviations.

This is a diagnostic only. It never guesses: a mapping is accepted only when the
normalized label resolves to exactly one ticker across the validated 2006/2010
Russell snapshots. The June 30 2007 IWV filed holdings remain the membership evidence.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path

import pit_russell_2007_iwv_name_map as base

ALIASES = {
    "COMPANIES": "COS",
    "COMPANY": "CO",
    "CORPORATION": "CORP",
    "INCORPORATED": "INC",
    "LIMITED": "LTD",
    "INTERNATIONAL": "INTL",
    "GROUP": "GRP",
    "HOLDINGS": "HLDG",
    "HOLDING": "HLDG",
    "MANUFACTURING": "MFG",
    "MATERIALS": "MATLS",
    "SERVICES": "SVCS",
    "PRODUCTS": "PRODS",
    "TECHNOLOGIES": "TECH",
    "TECHNOLOGY": "TECH",
    "COMMUNICATIONS": "COMM",
    "COMMUNICATION": "COMM",
    "FINANCIAL": "FINL",
    "INVESTMENTS": "INVT",
    "INVESTMENT": "INVT",
    "RESOURCES": "RES",
}


def signature(value: str) -> str:
    tokens=[]
    for token in base.canonical_company(value).split():
        if token == "THE":
            continue
        tokens.append(ALIASES.get(token, token))
    return " ".join(tokens)


def unique_ticker(items):
    tickers=sorted({x.ticker for x in items})
    return tickers[0] if len(tickers)==1 else None


def prefix_candidates(sig: str, sources):
    out=[]
    for item in sources:
        other=signature(item.company)
        shorter=other if len(other)<=len(sig) else sig
        if len(shorter)<6 or len(shorter.split())<2:
            continue
        if sig.startswith(other) or other.startswith(sig):
            out.append(item)
    return out


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--russell-2006',type=Path,required=True)
    p.add_argument('--russell-2010',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()

    holdings=base.extract_holdings(base.render_iwv_window(base.fetch_iwv_pdf()))
    sources=base.load_source(a.russell_2006,2006)+base.load_source(a.russell_2010,2010)
    raw_exact=base.build_indexes(sources)
    sig_exact={}
    for item in sources:
        sig_exact.setdefault(signature(item.company),[]).append(item)

    mapped=[]; ambiguous=[]; unmatched=[]; methods={}
    for h in holdings:
        canon=base.canonical_company(h.company)
        sig=signature(h.company)
        candidates=raw_exact.get(canon,[])
        ticker=unique_ticker(candidates)
        method='exact_canonical' if ticker else ''
        if not ticker:
            candidates=base.prefix_candidates(canon,sources)
            ticker=unique_ticker(candidates)
            method='literal_prefix' if ticker else ''
        if not ticker:
            candidates=sig_exact.get(sig,[])
            ticker=unique_ticker(candidates)
            method='abbreviation_signature_exact' if ticker else ''
        if not ticker:
            candidates=prefix_candidates(sig,sources)
            ticker=unique_ticker(candidates)
            method='abbreviation_signature_prefix' if ticker else ''
        if ticker:
            methods[method]=methods.get(method,0)+1
            mapped.append({'iwv_company':h.company,'signature':sig,'ticker':ticker,'method':method,'source_matches':[asdict(x) for x in candidates]})
        elif candidates:
            ambiguous.append({'iwv_company':h.company,'signature':sig,'candidate_tickers':sorted({x.ticker for x in candidates}),'source_matches':[asdict(x) for x in candidates]})
        else:
            unmatched.append({'iwv_company':h.company,'signature':sig})

    counts={}
    for row in mapped: counts[row['ticker']]=counts.get(row['ticker'],0)+1
    dup={k:v for k,v in sorted(counts.items()) if v>1}
    result={
        'schema':1,
        'source_role':'independent IWV June 30 2007 filed holdings identity diagnostic; not Russell membership authority',
        'iwv_holding_count':len(holdings),
        'method_counts':methods,
        'mapped_count':len(mapped),
        'ambiguous_count':len(ambiguous),
        'unmatched_count':len(unmatched),
        'duplicate_mapped_tickers':dup,
        'mapped':mapped,'ambiguous':ambiguous,'unmatched':unmatched,
    }
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
    print('holdings',len(holdings))
    print('mapped',len(mapped),methods)
    print('ambiguous',len(ambiguous))
    print('unmatched',len(unmatched))
    print('duplicate_mapped_tickers',dup)
    print('UNMATCHED_FIRST_100')
    for row in unmatched[:100]: print(row['iwv_company'],'=>',row['signature'])
    return 0

if __name__=='__main__':
    raise SystemExit(main())
