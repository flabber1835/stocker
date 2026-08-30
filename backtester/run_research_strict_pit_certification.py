#!/usr/bin/env python3
"""Strict-PIT retained-research certification wrapper.

The retained research mechanics stay frozen.  This wrapper changes only metadata
and reporting authority: historical price-tape security episodes, strict-prior
SEC issuer/sector evidence, positive-only SEC security type, PIT actions, and the
same causal Treasury/BIL cash model as production.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

os.environ["CERTIFICATION_STRICT_PIT"] = "1"

from backtester.strict_pit_metadata import authority_audit  # noqa: E402
import backtester.run_research_ldrc_corrected_warmup_cash as corrected  # noqa: E402

old = corrected.old
_original_transform = old.transformed_source


def _strict_transform(mode: str, output: Path) -> str:
    text = _original_transform(mode, output)
    if mode != "fullpit":
        return text

    start = text.index("def load_meta():")
    end = text.index("\ndef load_actions():", start)
    strict_load_meta = r'''def load_meta():
    global _PIT_EPISODES, _PIT_IDENTITY_AUDIT
    # Strict PIT: build identity solely from the historical SEP tape and
    # strict-prior SEC CIK-change boundaries. No current TICKERS field is read.
    dates=defaultdict(list)
    for _p in sorted(glob.glob(str(ROOT/'SHARADAR_SEP_*.csv*.gz'))):
        _q=pd.read_csv(_p,usecols=['ticker','date'],low_memory=False).dropna(subset=['ticker','date'])
        _q['ticker']=_q.ticker.astype(str); _q['date']=pd.to_datetime(_q.date).dt.strftime('%Y-%m-%d')
        _q=_q.drop_duplicates(['ticker','date'],keep='last')
        for _t,_g in _q.groupby('ticker',sort=False): dates[str(_t)].extend(_g.date.tolist())
    for _t in list(dates): dates[_t]=sorted(set(dates[_t]))
    _cik=pd.read_csv(Path('research/sentinel-fastgate/pit-evidence/generated/sec_cik_change_events.csv.gz'),compression='gzip',low_memory=False)
    _cik=_cik.sort_values(['ticker','filing_date'],kind='mergesort')
    changes=defaultdict(list)
    for _t,_g in _cik.groupby('ticker',sort=False):
        _prior=None
        for _r in _g.itertuples(index=False):
            _filed=str(_r.filing_date)[:10]
            try: _v=str(int(float(_r.issuer_cik)))
            except Exception: continue
            if _prior is None: _prior=_v
            elif _v!=_prior: changes[str(_t)].append(_filed); _prior=_v
    rows=[]; _PIT_EPISODES=defaultdict(list)
    for _t,_obs in sorted(dates.items()):
        if not _obs: continue
        _starts=[_obs[0]]
        for _cut in sorted(set(changes.get(_t,()))):
            _i=np.searchsorted(np.asarray(_obs,dtype='U10'),_cut,side='right')
            if _i<len(_obs): _starts.append(_obs[int(_i)])
        _starts=sorted(set(_starts))
        for _ep,_first in enumerate(_starts):
            _payload=f'PIT_SECURITY_V1|{_t}|{_first}|{_ep}'.encode()
            _sid=str(int(hashlib.sha256(_payload).hexdigest()[:15],16))
            rows.append((_t,_sid,_first,_ep))
    rows.sort(key=lambda z:(z[0],z[2],z[1]))
    tick=np.asarray([r[0] for r in rows],object)
    sid=np.asarray([r[1] for r in rows],object)
    fp=pd.to_datetime([r[2] for r in rows]).to_numpy('datetime64[D]')
    lp=np.full(len(rows),np.datetime64('2262-04-11'),dtype='datetime64[D]')
    tmap={}
    for i,r in enumerate(rows):
        tmap.setdefault(r[0],i); _PIT_EPISODES[r[0]].append((r[2],i))
    common=np.zeros(len(rows),bool)
    sector=np.asarray([None]*len(rows),object)
    exchange=np.asarray(['']*len(rows),object)
    issuer=np.asarray([None]*len(rows),object)
    _PIT_IDENTITY_AUDIT={
        'identity_authority':'historical SEP ticker observations plus strict-prior SEC CIK-change episode boundaries',
        'security_ids':len(rows),'tickers':len(_PIT_EPISODES),
        'cik_change_episode_boundaries':sum(max(0,len(v)-1) for v in _PIT_EPISODES.values()),
        'first_listing_authority':'first observed historical SEP price session',
        'last_listing_authority':'none; no future last-price date is admitted',
        'permaticker_authority':'none','related_tickers_authority':'none','exchange_authority':'none/non-authoritative'}
    return tick,tmap,sid,common,sector,exchange,fp,lp,issuer


def strict_tid(ticker, ds):
    xs=_PIT_EPISODES.get(str(ticker),())
    if not xs: return None
    s=str(ds)[:10]; starts=[x[0] for x in xs]; i=np.searchsorted(np.asarray(starts,dtype='U10'),s,side='right')-1
    return None if i<0 else int(xs[int(i)][1])
'''
    text = text[:start] + strict_load_meta + text[end:]

    init_needle = "actions,split_dates=load_actions(); spy,bil=load_funds(); book=Book(); native=Native()"
    strict_authority = r'''actions,split_dates=load_actions(); spy,bil=load_funds(); book=Book(); native=Native()
    _sec=pd.read_csv(Path('PIT input data/SEC_SECURITY_TYPE_POSITIVE_EVIDENCE.csv.gz'),compression='gzip',low_memory=False)
    _sec['ticker']=_sec.ticker.astype(str).str.upper(); _sec['filed']=_sec.filed.astype(str).str[:10]
    _sec=_sec.sort_values(['ticker','filed'],kind='mergesort')
    _sec_by={k:g.copy() for k,g in _sec.groupby('ticker',sort=False)}
    _manual={}
    _mp=Path('PIT input data/SEC_SECURITY_TYPE_MANUAL_ADMISSION_AUDIT.csv')
    if _mp.exists():
        _m=pd.read_csv(_mp,low_memory=False)
        _m=_m[_m.admission.astype(str).eq('admitted')]
        for _r in _m.itertuples(index=False):
            _manual[(str(_r.orion_ticker).upper(),str(_r.buy_date)[:10])]=str(_r.resolved_as).lower()
    _SEC_COUNTS={'auto_common':0,'manual_common':0,'manual_non_common':0,'unknown_ineligible':0}
    def common_key(tid, ds):
        ticker=str(tick[int(tid)]).upper(); session=str(ds)[:10]
        mv=_manual.get((ticker,session))
        if mv=='common': _SEC_COUNTS['manual_common']+=1; return True
        if mv=='non_common': _SEC_COUNTS['manual_non_common']+=1; return False
        q=_sec_by.get(ticker)
        if q is not None:
            q=q[q.filed<session]
            cik=pit_model._strict_prior(pit_model.cik_dates.get(ticker,()),pit_model.cik_values.get(ticker,()),session)
            if cik is not None and len(q):
                q=q[q.cik.map(lambda x: str(int(float(x))) if pd.notna(x) else '')==str(cik)]
            if len(q): _SEC_COUNTS['auto_common']+=1; return True
        _SEC_COUNTS['unknown_ineligible']+=1; return False'''
    if text.count(init_needle) != 1:
        raise RuntimeError(f"strict research init seam count={text.count(init_needle)}")
    text = text.replace(init_needle, strict_authority, 1)

    old_ids = "ids=d.ticker.astype(str).map(tmap); d=d[ids.notna()].copy(); d['tid']=ids[ids.notna()].astype(np.int32).to_numpy()"
    new_ids = "ids=pd.Series([strict_tid(t,ds) for t,ds in zip(d.ticker.astype(str),d.date.dt.strftime('%Y-%m-%d'))],index=d.index); d=d[ids.notna()].copy(); d['tid']=ids.loc[d.index].astype(np.int32).to_numpy()"
    if text.count(old_ids) != 1:
        raise RuntimeError("strict research price identity seam changed")
    text = text.replace(old_ids, new_ids, 1)

    old_listed = "dt64=np.datetime64(date.date()); listed=(firstdate[tids]<=dt64)&(lastdate[tids]>=dt64); continuous=c126[tids]>=126"
    new_listed = "dt64=np.datetime64(date.date()); listed=(firstdate[tids]<=dt64); continuous=c126[tids]>=126"
    if text.count(old_listed) != 1:
        raise RuntimeError("strict research listing seam changed")
    text = text.replace(old_listed, new_listed, 1)

    old_elig = "elig=common[tids]&listed&continuous&np.isfinite(mm)&np.isfinite(rr)&np.isfinite(cu)&(cu>=MIN_PRICE)&np.isfinite(av)&(av>=MIN_ADV20)&np.isfinite(dv)&(dv>=MIN_DAY_DV)&np.isfinite(sc)&(fvol>0)"
    new_elig = "elig=np.asarray([common_key(int(t),ds) for t in tids],dtype=bool)&listed&continuous&np.isfinite(mm)&np.isfinite(rr)&np.isfinite(cu)&(cu>=MIN_PRICE)&np.isfinite(av)&(av>=MIN_ADV20)&np.isfinite(dv)&(dv>=MIN_DAY_DV)&np.isfinite(sc)&(fvol>0)"
    if text.count(old_elig) != 1:
        raise RuntimeError("strict research security-type seam changed")
    text = text.replace(old_elig, new_elig, 1)

    text = text.replace(
        "term_tids={tmap[tk] for tk,rs in dayact.items() if tk in tmap and any(a in TERMINAL for a,_,_ in rs)}",
        "term_tids={z for tk,rs in dayact.items() if (z:=strict_tid(tk,ds)) is not None and any(a in TERMINAL for a,_,_ in rs)}",
        1,
    )
    text = text.replace(
        "if tk not in tmap: continue\n                tid=tmap[tk]; q=prior_qty.get(tid,0.)",
        "tid=strict_tid(tk,ds)\n                if tid is None: continue\n                q=prior_qty.get(tid,0.)",
        1,
    )

    sort_needle = "d.sort_values(['date','tid'],inplace=True,kind='mergesort')"
    text = text.replace(
        sort_needle,
        sort_needle + "\n        _quarter_last=set(pd.Timestamp(x) for x in d.groupby(d.date.dt.to_period('Q')).date.max())",
        1,
    )
    checkpoint = "prev_perf_date=date; prev_close_eq=eq"
    checkpoint_new = r'''if date in _quarter_last:
                    _elapsed=(date-START).days/365.2425
                    _cc=0.0 if _elapsed<=0 else float(navs['control'])**(1.0/_elapsed)-1.0
                    print(f'[CERT_CAGR] role=research date={ds} cagr={_cc:.12f}',flush=True)
                prev_perf_date=date; prev_close_eq=eq'''
    if text.count(checkpoint) != 1:
        raise RuntimeError("strict research checkpoint seam changed")
    text = text.replace(checkpoint, checkpoint_new, 1)

    evidence_needle = "'replay_mode':MODE,"
    text = text.replace(
        evidence_needle,
        evidence_needle + "\n        'strict_identity_audit':_PIT_IDENTITY_AUDIT,\n        'strict_security_type_counts':_SEC_COUNTS,",
        1,
    )

    forbidden = ["zcsv(ROOT/'SHARADAR_TICKERS.zip'", "common[tids]", "lastdate[tids]>=dt64", "d.ticker.astype(str).map(tmap)"]
    for needle in forbidden:
        if needle in text:
            raise RuntimeError(f"strict research transform retained forbidden current-metadata seam: {needle}")
    return text


old.transformed_source = _strict_transform


def _write_authority_audit(output: Path) -> None:
    summary_path = output / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    identity = summary.get("strict_identity_audit") or {}
    counts = summary.get("strict_security_type_counts") or {}
    security_type = {
        "authority": "SEC/EDGAR dated common/ordinary-equity evidence; filing/evidence date strictly prior to decision session",
        "observations_auto_common": int(counts.get("auto_common", 0)),
        "observations_manual_common": int(counts.get("manual_common", 0)),
        "observations_manual_non_common": int(counts.get("manual_non_common", 0)),
        "observations_unknown_ineligible": int(counts.get("unknown_ineligible", 0)),
        "unknown_policy": "ineligible",
    }
    audit = authority_audit(identity=identity, security_type=security_type)
    audit["role"] = "research"
    path = output / "metadata_authority_audit.json"
    path.write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    summary["strict_pit_metadata"] = True
    summary["metadata_authority_audit"] = audit
    summary["pit_authority"]["category"] = security_type["authority"]
    summary["pit_authority"]["identity"] = identity.get("identity_authority")
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    files = [output / "daily.csv.gz", output / "metrics.csv", summary_path, path]
    (output / "SHA256SUMS.txt").write_text(
        "".join(f"{old.sha256(p)}  {p.name}\n" for p in files), encoding="utf-8"
    )
    if audit["current_SHARADAR_TICKERS_economically_active_fields"]:
        raise RuntimeError("strict research retained current SHARADAR_TICKERS authority")


def main() -> int:
    print("[RUN] strict-PIT retained research certification", flush=True)
    rc = int(corrected.main())
    if rc != 0:
        return rc
    # corrected.main parses --output; recover it from argv.
    args = os.sys.argv[1:]
    try:
        output = Path(args[args.index("--output") + 1])
    except (ValueError, IndexError):
        raise RuntimeError("strict research wrapper requires --output")
    _write_authority_audit(output)
    print("[PASS] strict-PIT retained research certification bundle complete", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
