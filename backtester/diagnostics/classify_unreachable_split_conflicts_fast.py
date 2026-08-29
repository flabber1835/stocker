#!/usr/bin/env python3
"""Fast conservative reachability proof for the current 52 unresolved split events.

The target set is the certified 24-adjudication unresolved population minus the
52 subsequently frozen adjudications (76 total adjudicated, 52 raw unresolved).
For each event we resolve its permanent security identity from historical TICKERS
bounds and inspect every raw SEP ticker interval belonging to that identity.

PROVEN_UNREACHABLE requires that, from the fresh replay start through event+126
XNYS sessions, the security never passes all split-independent Wealth Core entry
gates. This does not use category, exchange, adjusted prices, momentum, or
volatility as exclusion evidence.
"""
from __future__ import annotations

from collections import defaultdict, deque
import json
import math
import os
from pathlib import Path
import zipfile

import numpy as np
import pandas as pd

CHAIN_START = "1998-01-02"
END_SESSION = "2026-07-31"
REQUIRED_CLOSES = 127
ADV_WINDOW = 20
CONTAMINATION_FUTURE_SESSIONS = 126
MIN_PRICE = 1.0
MIN_ADV20 = 20_000_000.0
MIN_SIGNAL_DV = 5_000_000.0

TARGET_EVENTS = tuple(line.split() for line in """
DAYR 1998-03-18
CCIL 1998-04-15
NSFC 1998-04-23
ICIX 1998-06-16
CIBN1 1998-09-01
CVAL 1998-09-02
FCEC 1998-11-25
SMRL 1999-01-15
NSDB 1999-01-29
MODM 1999-03-12
TVLI 1999-03-26
WTR1 1999-03-29
BMAN 1999-07-15
CRSC 1999-07-30
SSC1 1999-08-06
BZBC 1999-08-30
OSFT 1999-10-13
SUMM1 1999-11-10
HBEK 2000-01-26
NBAN 2000-02-28
CFCP 2000-03-24
NSDB 2000-04-27
SWIM1 2000-05-12
TMAV1 2000-08-08
UTI1 2000-10-03
SWIM1 2000-11-15
SWIM1 2001-05-15
DEAR 2001-05-29
PFI1 2001-07-02
SWIM1 2001-11-14
NBAN 2002-02-28
SWIM1 2002-05-14
SWIM1 2002-11-13
SUMM1 2002-11-20
FBGI1 2002-11-29
SSLI 2003-04-02
NREB 2003-05-07
NCRI 2003-06-16
SAMB 2003-07-15
PNOT 2003-07-30
SEM2 2003-12-23
FNSCQ 2004-03-01
NSDB 2004-04-29
FSNMQ 2005-02-09
FCEC 2005-04-28
AAWW 2006-04-03
MBCRQ 2006-06-20
ETELY 2007-09-04
STB 2013-05-20
MHGVY 2014-05-01
PRPO 2017-06-06
GHI 2022-12-29
""".strip().splitlines())


def norm_id(v):
    if v is None or pd.isna(v):
        return None
    try:
        return str(int(float(v)))
    except (TypeError, ValueError, OverflowError):
        s = str(v).strip()
        return s or None


def finite(v):
    try:
        return math.isfinite(float(v))
    except (TypeError, ValueError):
        return False


def load_tickers(path: Path):
    with zipfile.ZipFile(path) as z:
        names = [n for n in z.namelist() if n.lower().endswith('.csv')]
        if len(names) != 1:
            raise RuntimeError(f"unexpected TICKERS archive: {names}")
        with z.open(names[0]) as f:
            df = pd.read_csv(f, usecols=['table','permaticker','ticker','firstpricedate','lastpricedate'], low_memory=False)
    df = df[df.table.astype(str).eq('SEP') & df.permaticker.notna() & df.ticker.notna()].copy()
    df['sid'] = df.permaticker.map(norm_id)
    df['ticker'] = df.ticker.astype(str)
    df['first'] = df.firstpricedate.fillna('0001-01-01').astype(str).str[:10]
    df['last'] = df.lastpricedate.fillna('9999-12-31').astype(str).str[:10]
    return df[df.sid.notna()].copy()


def main() -> int:
    if len(TARGET_EVENTS) != 52 or len(set(map(tuple, TARGET_EVENTS))) != 52:
        raise RuntimeError('target population must contain exactly 52 unique events')
    root = Path(os.environ.get('BACKTESTER_LAB_ROOT', '.')).resolve()
    out = Path(os.environ.get('BACKTESTER_SPLIT_UNREACHABLE_FAST_OUTPUT',
        'backtester-results/split-unreachable-fast.json')).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    sfp = pd.read_csv(root/'PIT input data'/'SFP_SPY_BIL_PRICE_FACTORS_PIT_ONLY.csv.gz',
                      compression='gzip', usecols=['ticker','date'], low_memory=False)
    sessions = sorted(set(sfp.loc[sfp.ticker.astype(str).eq('SPY'),'date'].astype(str).str[:10]))
    sessions = [s for s in sessions if CHAIN_START <= s <= END_SESSION]
    sidx = {s:i for i,s in enumerate(sessions)}
    if not sessions or sessions[0] != CHAIN_START or sessions[-1] != END_SESSION:
        raise RuntimeError(f'unexpected replay axis {sessions[:1]} {sessions[-1:]}')

    tickers = load_tickers(root/'sharadar'/'SHARADAR_TICKERS.zip')
    by_ticker = defaultdict(list)
    for r in tickers.itertuples(index=False):
        by_ticker[r.ticker].append((r.first,r.last,r.sid))

    def resolve(ticker, session):
        active = {sid for first,last,sid in by_ticker.get(ticker,()) if first <= session <= last}
        return next(iter(active)) if len(active)==1 else None

    event_rows = []
    target_sids = set()
    bad_identity = []
    for ticker, session in TARGET_EVENTS:
        sid = resolve(ticker, session)
        if sid is None:
            bad_identity.append({'ticker':ticker,'session':session})
        else:
            target_sids.add(sid)
        event_rows.append({'ticker':ticker,'session':session,'security_id':sid})

    sid_tickers = defaultdict(set)
    for r in tickers.itertuples(index=False):
        if r.sid in target_sids:
            sid_tickers[r.sid].add(r.ticker)
    relevant_tickers = sorted(set().union(*(sid_tickers[s] for s in target_sids))) if target_sids else []

    # State is keyed by permanent identity and only uses split-independent raw facts.
    last_idx = {}
    contiguous = defaultdict(int)
    dv20 = defaultdict(lambda: deque(maxlen=ADV_WINDOW))
    ever_pass = defaultdict(bool)
    first_pass = {}
    passes_by_sid = defaultdict(list)
    rows_seen = 0

    for year in range(1998, 2027):
        candidates = sorted((root/'sharadar').glob(f'SHARADAR_SEP_{year}*.csv.gz'))
        if len(candidates) != 1:
            raise RuntimeError(f'expected one SEP file for {year}, found {candidates}')
        frame = pd.read_csv(candidates[0], usecols=['ticker','date','closeunadj','volume'], low_memory=False)
        frame['ticker'] = frame.ticker.astype(str)
        frame['date'] = frame.date.astype(str).str[:10]
        frame = frame[frame.ticker.isin(relevant_tickers) & frame.date.between(CHAIN_START, END_SESSION)].copy()
        frame['_seq'] = np.arange(len(frame), dtype=np.int64)
        frame.sort_values(['date','ticker','_seq'], inplace=True, kind='mergesort')
        frame.drop_duplicates(['date','ticker'], keep='last', inplace=True)
        for r in frame.itertuples(index=False):
            idx = sidx.get(r.date)
            if idx is None:
                continue
            sid = resolve(r.ticker, r.date)
            if sid not in target_sids:
                continue
            rows_seen += 1
            if last_idx.get(sid) != idx-1:
                contiguous[sid] = 0
                dv20[sid].clear()
            raw = float(r.closeunadj) if finite(r.closeunadj) else None
            vol = float(r.volume) if finite(r.volume) else None
            valid_close = raw is not None and raw > 0
            valid_dv = valid_close and vol is not None and vol >= 0
            if valid_close:
                contiguous[sid] += 1
            else:
                contiguous[sid] = 0
            if valid_dv:
                dv20[sid].append(raw*vol)
            else:
                dv20[sid].clear()
            current_dv = raw*vol if valid_dv else None
            adv = sum(dv20[sid])/ADV_WINDOW if len(dv20[sid])==ADV_WINDOW else None
            passed = bool(contiguous[sid] >= REQUIRED_CLOSES and raw is not None and raw >= MIN_PRICE
                          and current_dv is not None and current_dv >= MIN_SIGNAL_DV
                          and adv is not None and adv >= MIN_ADV20)
            if passed:
                passes_by_sid[sid].append(r.date)
                if not ever_pass[sid]:
                    ever_pass[sid]=True
                    first_pass[sid]=r.date
            last_idx[sid]=idx
        print(f'[FAST-UNREACHABLE] year={year} target_rows={rows_seen:,}', flush=True)

    unreachable=[]
    blocking=[]
    for ev in event_rows:
        ticker, session, sid = ev['ticker'], ev['session'], ev['security_id']
        if sid is None or session not in sidx:
            blocking.append({**ev,'reachability':'BLOCKING','reason':'UNRESOLVED_IDENTITY_OR_SESSION'})
            continue
        ei=sidx[session]
        hi=min(ei+CONTAMINATION_FUTURE_SESSIONS,len(sessions)-1)
        horizon=sessions[hi]
        dates=passes_by_sid.get(sid,[])
        prior=[d for d in dates if d <= session]
        contam=[d for d in dates if session <= d <= horizon]
        safe=not prior and not contam
        row={**ev,
             'identity_tickers':sorted(sid_tickers[sid]),
             'proof_horizon_session':horizon,
             'pass_on_or_before_event':bool(prior),
             'first_prior_pass_session':prior[0] if prior else None,
             'pass_during_contamination':bool(contam),
             'first_contamination_pass_session':contam[0] if contam else None,
             'reachability':'PROVEN_UNREACHABLE' if safe else 'BLOCKING'}
        (unreachable if safe else blocking).append(row)

    payload={
      'schema':'backtester.split-unreachable-fast/1',
      'status':'PASS',
      'diagnostic_only':True,
      'backtester_sha':os.environ.get('BACKTESTER_BRANCH_SHA'),
      'chain_start':CHAIN_START,'end_session':END_SESSION,
      'target_event_count':52,'target_identity_count':len(target_sids),
      'target_raw_rows_examined':rows_seen,
      'identity_failures':bad_identity,
      'proof_rule':{'min_unadjusted_price':MIN_PRICE,'min_adv20_dollars':MIN_ADV20,
        'min_signal_dollar_volume':MIN_SIGNAL_DV,'required_contiguous_closes':REQUIRED_CLOSES,
        'contamination_future_sessions':CONTAMINATION_FUTURE_SESSIONS,
        'category_used':False,'exchange_used':False,'adjusted_price_used':False},
      'proven_unreachable_count':len(unreachable),
      'blocking_unresolved_count':len(blocking),
      'proven_unreachable':unreachable,'blocking_unresolved':blocking}
    if len(unreachable)+len(blocking)!=52:
        raise RuntimeError('classification population mismatch')
    out.write_text(json.dumps(payload,indent=2,sort_keys=True)+'\n',encoding='utf-8')
    print(json.dumps({'status':'PASS','unreachable':len(unreachable),'blocking':len(blocking),
                      'identity_failures':len(bad_identity)},sort_keys=True),flush=True)
    return 0

if __name__=='__main__':
    raise SystemExit(main())
