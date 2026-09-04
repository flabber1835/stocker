#!/usr/bin/env python3
"""Build causal IWB/R1000 proxy snapshots bound to contemporaneous SEP tickers.

The R1000/IWB snapshot is the eligibility authority. Sharadar TICKERS is used
only as a CUSIP crosswalk where useful; its current category, issuer, sector,
and listing-date bounds are not strategy inputs. A mapping is accepted only if
the resulting ticker actually appears in Sharadar SEP during that snapshot
month. No company-name fuzzy matching is allowed.
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import re
import time
import urllib.parse
import urllib.request
import zipfile
from collections import defaultdict
from pathlib import Path

import pandas as pd

API_URLS = (
    "https://www.ishares.com/varnish-api/blk-one01-product-data/product-data/api/v2/get-product-data",
    "https://www.blackrock.com/varnish-api/blk-one01-product-data/product-data/api/v2/get-product-data",
)
PRODUCT_ID = "239707"
USER_AGENT = "Mozilla/5.0 (compatible; Stocker-R1000-PIT-research/1.0)"
KNOWN_CLASS_ALIASES = {
    "BRKA": "BRK.A", "BRKB": "BRK.B", "BFA": "BF.A", "BFB": "BF.B", "HEIA": "HEI.A",
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''): h.update(chunk)
    return h.hexdigest()


def compact(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value).upper().replace("*", ""))


def norm_cusip(value) -> str | None:
    if value is None or pd.isna(value): return None
    text=re.sub(r"[^A-Z0-9]", "", str(value).upper())
    return text if len(text) in (8,9) else None


def load_cusip_crosswalk(path: Path) -> dict[str,set[str]]:
    with zipfile.ZipFile(path) as zf:
        members=[n for n in zf.namelist() if n.lower().endswith('.csv')]
        if len(members)!=1: raise RuntimeError(f'{path}: expected one CSV')
        with zf.open(members[0]) as f:
            frame=pd.read_csv(f,usecols=['table','ticker','cusips'],low_memory=False)
    frame=frame[frame.table.astype(str).eq('SEP') & frame.ticker.notna()].copy()
    out=defaultdict(set)
    for row in frame.itertuples(index=False):
        ticker=str(row.ticker).strip().upper()
        if not ticker or pd.isna(row.cusips): continue
        for token in re.split(r"[\s,;|]+",str(row.cusips).upper()):
            c=norm_cusip(token)
            if c: out[c].add(ticker)
    return dict(out)


def year_file(root: Path, year: int) -> Path:
    paths=sorted(root.glob(f'SHARADAR_SEP_{year}.csv*.gz'))
    if not paths: raise FileNotFoundError(f'no SEP file for {year}')
    if len(paths)>1:
        hashes=[sha256_file(p) for p in paths]
        if len(set(hashes))!=1: raise RuntimeError(f'non-identical SEP duplicates for {year}')
    return paths[0]


def load_sep_month_tickers(root: Path, year: int) -> dict[str,set[str]]:
    frame=pd.read_csv(year_file(root,year),usecols=['ticker','date'],low_memory=False)
    frame=frame[frame.ticker.notna() & frame.date.notna()].copy()
    frame['ticker']=frame.ticker.astype(str).str.upper()
    frame['month']=frame.date.astype(str).str[:7]
    return {month:set(g.ticker) for month,g in frame.groupby('month',sort=False)}


def vals(dp: dict, name: str) -> list:
    p=dp.get(name,{}) if isinstance(dp,dict) else {}
    v=p.get('value') if isinstance(p,dict) else None
    if isinstance(v,list): return v
    v=p.get('formattedValue') if isinstance(p,dict) else None
    return v if isinstance(v,list) else []


def fetch_snapshot(candidate: pd.Timestamp, timeout: int=45) -> dict:
    d=candidate.strftime('%Y%m%d')
    params={'appType':'PRODUCT_PAGE','appSubType':'ISHARES','targetSite':'us-ishares','locale':'en_US','portfolioId':PRODUCT_ID,'userType':'individual','component':'holdings','asOfDate':d}
    errors=[]
    for base in API_URLS:
        url=base+'?'+urllib.parse.urlencode(params)
        try:
            req=urllib.request.Request(url,headers={'User-Agent':USER_AGENT,'Accept':'application/json'})
            with urllib.request.urlopen(req,timeout=timeout) as response: raw=response.read()
            payload=json.loads(raw.decode('utf-8-sig'))
            dp=payload['componentsByNameMap']['holdings']['containersByNameMap']['all']['dataPointsByNameMap']
            tickers=vals(dp,'ticker'); assets=vals(dp,'assetClass'); cusips=vals(dp,'cusip')
            asof=(dp.get('asOfDate') or {}).get('value') or (dp.get('asOfDate') or {}).get('formattedValue') or d
            text=str(asof).strip(); asof_ts=pd.to_datetime(text,format='%Y%m%d').normalize() if re.fullmatch(r'\d{8}',text) else pd.Timestamp(text).normalize()
            rows=[]
            for i,t in enumerate(tickers):
                raw_ticker=str(t).strip().upper()
                if not raw_ticker or raw_ticker=='-': continue
                asset=str(assets[i]).strip() if i<len(assets) else 'Equity'
                if asset and asset.lower()!='equity': continue
                rows.append({'raw_ticker':raw_ticker,'cusip':norm_cusip(cusips[i]) if i<len(cusips) else None})
            if len(rows)<850: raise ValueError(f'implausibly small IWB equity holdings: {len(rows)}')
            return {'source_url':url,'source_sha256':sha256_bytes(raw),'source_bytes':len(raw),'as_of_date':asof_ts.strftime('%Y-%m-%d'),'rows':rows}
        except Exception as exc:
            errors.append(f'{base}: {type(exc).__name__}: {exc}')
    raise RuntimeError('; '.join(errors))


def resolve_snapshot(requested: pd.Timestamp,max_lookback_days:int=7) -> dict:
    errors=[]
    for delta in range(max_lookback_days+1):
        candidate=requested-pd.Timedelta(days=delta)
        try: snap=fetch_snapshot(candidate)
        except Exception as exc:
            errors.append(f'{candidate.date()}: {exc}'); continue
        if pd.Timestamp(snap['as_of_date'])>requested:
            errors.append(f"{candidate.date()}: future as-of {snap['as_of_date']}"); continue
        snap['requested_date']=requested.strftime('%Y-%m-%d'); snap['lookback_days']=delta
        return snap
    raise RuntimeError(f'no IWB snapshot before {requested.date()}: '+ ' | '.join(errors[-4:]))


def request_dates(start:str,end:str) -> list[pd.Timestamp]:
    s=pd.Timestamp(start).normalize(); e=pd.Timestamp(end).normalize()
    xs=[pd.Timestamp(x).normalize() for x in pd.date_range(s,e,freq='ME')]
    if not xs or xs[0]>s: xs.insert(0,s)
    if xs[-1]!=e: xs.append(e)
    return sorted(set(xs))


def choose_ticker(raw:str,cusip:str|None,month_tickers:set[str],cusip_map) -> tuple[str|None,str]:
    cleaned=str(raw).upper().rstrip('*').strip()
    if cleaned in month_tickers: return cleaned,'exact_sep_month'
    alias=KNOWN_CLASS_ALIASES.get(compact(cleaned))
    if alias and alias in month_tickers: return alias,'known_class_alias'
    if cusip:
        candidates=sorted(set(cusip_map.get(cusip,set())).intersection(month_tickers))
        if len(candidates)==1: return candidates[0],'cusip_sep_month'
    key=compact(cleaned)
    candidates=sorted(t for t in month_tickers if compact(t)==key)
    if len(candidates)==1: return candidates[0],'punctuation_sep_month'
    return None,'unmapped'


def main() -> int:
    ap=argparse.ArgumentParser()
    ap.add_argument('--tickers',type=Path,required=True)
    ap.add_argument('--sep-root',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--start',default='2006-09-29'); ap.add_argument('--end',default='2026-07-31')
    ap.add_argument('--min-coverage',type=float,default=.90)
    args=ap.parse_args(); args.output.mkdir(parents=True,exist_ok=True)
    cusip_map=load_cusip_crosswalk(args.tickers)
    rows=[]; manifest=[]; seen=set(); year_cache_year=None; month_tickers_by_month={}
    dates=request_dates(args.start,args.end)
    for number,requested in enumerate(dates,1):
        snap=resolve_snapshot(requested); asof=snap['as_of_date']
        if asof in seen: continue
        seen.add(asof); year=int(asof[:4])
        if year_cache_year!=year:
            month_tickers_by_month=load_sep_month_tickers(args.sep_root,year); year_cache_year=year
        month=asof[:7]; month_tickers=month_tickers_by_month.get(month,set())
        if not month_tickers: raise RuntimeError(f'no SEP tickers in month {month}')
        methods=defaultdict(int); unmapped=[]; mapped=[]
        raw_unique={}
        for item in snap.pop('rows'):
            raw_unique[(item['raw_ticker'],item.get('cusip'))]=item
        for item in raw_unique.values():
            ticker,method=choose_ticker(item['raw_ticker'],item.get('cusip'),month_tickers,cusip_map)
            methods[method]+=1
            if ticker is None: unmapped.append(item['raw_ticker']); continue
            mapped.append((item['raw_ticker'],item.get('cusip'),ticker,method))
        mapped_unique=sorted({x[2] for x in mapped}); coverage=len(mapped_unique)/len(raw_unique) if raw_unique else 0.
        if coverage<args.min_coverage:
            raise RuntimeError(f'IWB->SEP coverage too low {asof}: {len(mapped_unique)}/{len(raw_unique)}={coverage:.2%}; sample={unmapped[:30]}')
        for raw,cusip,ticker,method in mapped:
            rows.append({'as_of_date':asof,'ticker':ticker,'raw_iwb_ticker':raw,'cusip':cusip,'mapping_method':method})
        manifest.append({**snap,'raw_equity_count':len(raw_unique),'mapped_unique_tickers':len(mapped_unique),'mapping_coverage':coverage,'mapping_methods':dict(methods),'unmapped_count':len(unmapped),'unmapped_sample':unmapped[:30]})
        if number%12==0 or number==len(dates): print(f'[R1000] {asof} raw={len(raw_unique)} mapped={len(mapped_unique)} coverage={coverage:.2%} requests={number}/{len(dates)}',flush=True)
        time.sleep(.02)
    out=pd.DataFrame(rows).drop_duplicates(['as_of_date','ticker'],keep='first').sort_values(['as_of_date','ticker'])
    out_path=args.output/'r1000_iwb_snapshots.csv.gz'; out.to_csv(out_path,index=False,compression={'method':'gzip','compresslevel':6,'mtime':0})
    summary={'schema':'backtester.r1000-iwb-sep-proxy/1','status':'PASS','evidence_label':'BEST_EFFORT_PIT_R1000_IWB_PROXY','source':'BlackRock/iShares product-data v2 historical IWB holdings','identity_join':'contemporaneous monthly Sharadar SEP ticker; exact, CUSIP, or bounded punctuation only','causal_rule':'snapshot as-of t is eligible only for decision sessions strictly after t','requested_start':args.start,'requested_end':args.end,'snapshot_count':len(manifest),'first_as_of':min(x['as_of_date'] for x in manifest),'last_as_of':max(x['as_of_date'] for x in manifest),'minimum_mapping_coverage':min(x['mapping_coverage'] for x in manifest),'median_mapping_coverage':float(pd.Series([x['mapping_coverage'] for x in manifest]).median()),'snapshots':manifest,'output_sha256':sha256_file(out_path)}
    (args.output/'r1000_iwb_membership_manifest.json').write_text(json.dumps(summary,indent=2,sort_keys=True)+'\n',encoding='utf-8')
    print(f"[PASS] snapshots={len(manifest)} first={summary['first_as_of']} last={summary['last_as_of']} min_mapping={summary['minimum_mapping_coverage']:.2%}",flush=True)
    return 0

if __name__=='__main__': raise SystemExit(main())
