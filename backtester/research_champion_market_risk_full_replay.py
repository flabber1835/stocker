#!/usr/bin/env python3
"""Exact full-replay harness for classification-independent LDRC research.

RESEARCH / NOT CERTIFIED.

The corrected Research Champion Wealth Core, universe, classification layer,
execution, sizing, Native Sentinel, costs and cash mechanics remain frozen.
Only Candidate A / control's LDRC market-risk observation layer is replaced.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

import pandas as pd

from backtester import research_champion_corrected_classification as corrected
from backtester import run_research_champion_pit_closure_20y as closure

STATUS = "RESEARCH / NOT CERTIFIED"
SUPPORTED = {"current", "spy_price", "spy_vol", "vix_level_change", "vix_percentile", "spy_vix"}


def _once(text: str, old: str, new: str, label: str) -> str:
    n = text.count(old)
    if n != 1:
        raise RuntimeError(f"{label}: expected one source seam, found {n}")
    return text.replace(old, new, 1)


def _replace_block(text: str, start: str, end: str, replacement: str, label: str) -> str:
    if text.count(start) != 1 or text.count(end) != 1:
        raise RuntimeError(f"{label}: block anchors changed")
    i = text.index(start)
    j = text.index(end, i)
    return text[:i] + replacement.rstrip() + "\n\n" + text[j:]


def _market_candidate_source(family: str, params: dict) -> str:
    return f'''MARKET_RISK_FAMILY={family!r}
MARKET_RISK_PARAMS={params!r}

class CandidateA:
    """LDRC with classification-independent market-risk observations."""
    def __init__(self):
        self.episode=False; self.latched=False; self.full_streak=0
        self.prev_native=1.; self.prev_desired=1.; self.episodes=0
        self.market_entries=0; self.market_releases=0

    def _signals(self,spy20,spy40,spydd,rv20,volratio,vix,vixchg5,vixz,vixpct):
        p=MARKET_RISK_PARAMS; f=MARKET_RISK_FAMILY
        if f=='spy_price':
            stress=(finite(spy20) and finite(spydd) and
                    (spy20<=p['r20_stress'] or spydd<=p['dd_stress']))
            healthy=(finite(spy20) and finite(spy40) and
                     spy20>p.get('r20_healthy',0.) and spy40>p.get('r40_healthy',0.))
            rebound=finite(spy20) and spy20>=p['rebound']
        elif f=='spy_vol':
            stress=(finite(rv20) and finite(volratio) and
                    rv20>=p['rv20_stress'] and volratio>=p['ratio_stress'])
            healthy=(finite(rv20) and finite(volratio) and
                     rv20<=p['rv20_healthy'] and volratio<=p.get('ratio_healthy',1.))
            rebound=healthy
        elif f=='vix_level_change':
            stress=(finite(vix) and finite(vixchg5) and
                    vix>=p['vix_stress'] and vixchg5>=p['chg5_stress'])
            healthy=(finite(vix) and finite(vixchg5) and
                     vix<=p['vix_healthy'] and vixchg5<=p.get('chg5_healthy',0.))
            rebound=healthy
        elif f=='vix_percentile':
            stress=(finite(vixpct) and finite(vixz) and
                    vixpct>=p['pct_stress'] and vixz>=p['z_stress'])
            healthy=finite(vixpct) and vixpct<=p['pct_healthy']
            rebound=healthy
        elif f=='spy_vix':
            spy_stress=(finite(spy20) and finite(spydd) and
                        (spy20<=p['r20_stress'] or spydd<=p['dd_stress']))
            vix_stress=(finite(vix) and finite(vixz) and
                        (vix>=p['vix_stress'] or vixz>=p['z_stress']))
            stress=spy_stress and vix_stress
            healthy=(finite(spy20) and finite(spy40) and finite(vix) and
                     spy20>0. and spy40>0. and vix<=p['vix_healthy'])
            rebound=(finite(spy20) and finite(vixchg5) and
                     (spy20>=p['rebound'] or vixchg5<=p['vix_rebound_chg5']))
        else:
            raise RuntimeError(f'unsupported market-risk family: {{f}}')
        return bool(stress),bool(healthy),bool(rebound)

    def step(self,native,effective_native,wcdd,spy20,spy40,spydd,rv20,volratio,vix,vixchg5,vixz,vixpct):
        stress,healthy,rebound=self._signals(spy20,spy40,spydd,rv20,volratio,vix,vixchg5,vixz,vixpct)
        self.full_streak=self.full_streak+1 if healthy else 0
        reasons=[]
        if self.prev_native>=1-1e-12 and native<1-1e-12:
            if not self.episode: self.episodes+=1
            self.episode=True; reasons.append('RECOVERY_EPISODE_START')
        cleared=self.latched and (self.full_streak>=LDRC_REC or rebound)
        if cleared:
            self.latched=False; self.market_releases+=1; reasons.append('MARKET_RISK_CLEAR')
        desired=native
        if self.episode and native>=1-1e-12:
            if self.full_streak>=LDRC_REC or rebound:
                self.episode=False; desired=1.; self.market_releases+=1
                reasons.append('FULL_RISK_MARKET_RECOVERY')
            else:
                desired=self.prev_desired; reasons.append('FULL_RISK_HELD')
        avail=finite(wcdd) and effective_native is not None and finite(effective_native)
        if not self.latched and not cleared:
            entry=(native>=1-1e-12 and effective_native is not None and finite(effective_native)
                   and effective_native>=1-1e-12 and avail and wcdd<=LDRC_DD and stress)
            if entry:
                self.latched=True; self.market_entries+=1; reasons.append('MARKET_RISK_ENTER')
        if self.latched: desired=min(desired,LDRC_CEIL)
        desired=min(native,desired)
        self.prev_native=native; self.prev_desired=desired
        return float(desired),'|'.join(reasons) if reasons else 'NORMAL'
'''


def install_market_observations(text: str, family: str, params: dict) -> str:
    if family not in SUPPORTED:
        raise RuntimeError(f"unsupported family {family}")

    old_funds = """    spy['ret']=spy.closeadj.astype(float).pct_change(); spy['r20']=spy.closeadj.astype(float).pct_change(20)
    spy['volacc']=spy.ret.rolling(5).std(ddof=1)/spy.ret.rolling(20).std(ddof=1)-1
    cash=_CANONICAL.cash_factors()
"""
    new_funds = """    spy['ret']=spy.closeadj.astype(float).pct_change(); spy['r20']=spy.closeadj.astype(float).pct_change(20)
    spy['r40']=spy.closeadj.astype(float).pct_change(40)
    spy['volacc']=spy.ret.rolling(5).std(ddof=1)/spy.ret.rolling(20).std(ddof=1)-1
    spy['rv20']=spy.ret.rolling(20).std(ddof=1)*np.sqrt(252.)
    spy['rv40']=spy.ret.rolling(40).std(ddof=1)*np.sqrt(252.)
    spy['volratio']=spy['rv20']/spy['rv40']
    spy['dd']=spy.closeadj.astype(float)/spy.closeadj.astype(float).cummax()-1.
    _vix_raw=pd.read_csv(Path(os.environ['MARKET_RISK_VIX_CSV']))
    _vix_names={str(c).strip().upper():c for c in _vix_raw.columns}
    _vix_date=_vix_names.get('DATE') or _vix_names.get('OBSERVATION_DATE')
    _vix_close=_vix_names.get('CLOSE') or _vix_names.get('VIXCLS') or _vix_names.get('VIX')
    if _vix_date is None or _vix_close is None: raise RuntimeError(f'unsupported VIX columns: {list(_vix_raw.columns)}')
    _vix=_vix_raw[[_vix_date,_vix_close]].copy(); _vix.columns=['date','vix']
    _vix['date']=pd.to_datetime(_vix['date'],errors='coerce'); _vix['vix']=pd.to_numeric(_vix['vix'],errors='coerce')
    _vix=_vix.dropna().drop_duplicates('date',keep='last').sort_values('date').set_index('date')
    _vix['vixchg5']=_vix['vix'].pct_change(5); _vix['vixchg20']=_vix['vix'].pct_change(20)
    _roll=_vix['vix'].rolling(252,min_periods=126)
    _vix['vixz']=(_vix['vix']-_roll.mean())/_roll.std(ddof=1)
    _vix['vixpct']=_vix['vix'].rolling(252,min_periods=126).apply(lambda a:float(np.mean(a<=a[-1])),raw=True)
    spy=spy.join(_vix,how='left')
    for _c in ('vix','vixchg5','vixchg20','vixz','vixpct'): spy[_c]=spy[_c].ffill(limit=1)
    cash=_CANONICAL.cash_factors()
"""
    text = _once(text, old_funds, new_funds, "market feature load")

    old_obs = """            spy20=float(spy.loc[date,'r20']) if date in spy.index and finite(spy.loc[date,'r20']) else None
            volacc=float(spy.loc[date,'volacc']) if date in spy.index and finite(spy.loc[date,'volacc']) else None
            native_target,fastsig,slowsig=native.step((dd,r5,r10,r20,r40,dam_b,green_b,ddam5,spy20,volacc,stops20,eq))
"""
    new_obs = """            spy20=float(spy.loc[date,'r20']) if date in spy.index and finite(spy.loc[date,'r20']) else None
            spy40=float(spy.loc[date,'r40']) if date in spy.index and finite(spy.loc[date,'r40']) else None
            spydd=float(spy.loc[date,'dd']) if date in spy.index and finite(spy.loc[date,'dd']) else None
            rv20=float(spy.loc[date,'rv20']) if date in spy.index and finite(spy.loc[date,'rv20']) else None
            volratio=float(spy.loc[date,'volratio']) if date in spy.index and finite(spy.loc[date,'volratio']) else None
            vix=float(spy.loc[date,'vix']) if date in spy.index and finite(spy.loc[date,'vix']) else None
            vixchg5=float(spy.loc[date,'vixchg5']) if date in spy.index and finite(spy.loc[date,'vixchg5']) else None
            vixz=float(spy.loc[date,'vixz']) if date in spy.index and finite(spy.loc[date,'vixz']) else None
            vixpct=float(spy.loc[date,'vixpct']) if date in spy.index and finite(spy.loc[date,'vixpct']) else None
            volacc=float(spy.loc[date,'volacc']) if date in spy.index and finite(spy.loc[date,'volacc']) else None
            native_target,fastsig,slowsig=native.step((dd,r5,r10,r20,r40,dam_b,green_b,ddam5,spy20,volacc,stops20,eq))
"""
    text = _once(text, old_obs, new_obs, "market feature observations")

    row_old = "'recent_r20':recent_r20,'recent_r40':recent_r40,'spy_r20':spy20,'native_close_target':native_target,"
    row_new = "'recent_r20':recent_r20,'recent_r40':recent_r40,'spy_r20':spy20,'spy_r40':spy40,'spy_dd':spydd,'spy_rv20':rv20,'spy_vol_ratio':volratio,'vix':vix,'vix_chg5':vixchg5,'vix_z252':vixz,'vix_pct252':vixpct,'native_close_target':native_target,"
    text = _once(text, row_old, row_new, "market feature telemetry")

    if family != "current":
        text = _replace_block(text, "class CandidateA:\n", "class CandidateB:\n", _market_candidate_source(family, params), "CandidateA replacement")
        old_call = "a_d,a_reason=ca.step(native_target,effective_native,dd,recent_r20,recent_r40,spy20,r20)"
        new_call = "a_d,a_reason=ca.step(native_target,effective_native,dd,spy20,spy40,spydd,rv20,volratio,vix,vixchg5,vixz,vixpct)"
        text = _once(text, old_call, new_call, "CandidateA market call")

    compile(text, "<research-champion-market-risk-full-replay>", "exec")
    return text


def _sha256(path: Path) -> str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''): h.update(chunk)
    return h.hexdigest()


def _mark_outputs(output: Path, family: str, params: dict, vix_csv: Path) -> None:
    for name in ("summary.json", "pit-closure-replay-identity.json"):
        path=output/name
        if not path.exists(): continue
        doc=json.loads(path.read_text())
        doc.update(status=STATUS, certification_status="NOT_CERTIFIED",
                   market_risk_controller_family=family,
                   market_risk_controller_params=params,
                   leadership_observation_active=(family=="current"),
                   vix_source="Cboe VIX Index historical daily close",
                   vix_source_sha256=_sha256(vix_csv))
        path.write_text(json.dumps(doc,indent=2,sort_keys=True)+"\n")
    daily=output/"daily.csv.gz"
    if daily.exists():
        d=pd.read_csv(daily)
        d["market_risk_controller_family"]=family
        d["leadership_observation_active"]=(family=="current")
        d.to_csv(daily,index=False,compression={"method":"gzip","mtime":0})
    metrics=output/"metrics.csv"
    if metrics.exists():
        m=pd.read_csv(metrics); m["market_risk_controller_family"]=family
        m["market_risk_controller_params"]=json.dumps(params,sort_keys=True,separators=(",",":"))
        m.to_csv(metrics,index=False)
    manifest={
        "status":STATUS,
        "family":family,
        "params":params,
        "leadership_observation_active":family=="current",
        "classification_independent_controller_observation":family!="current",
        "vix_source_url":"https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv",
        "vix_source_sha256":_sha256(vix_csv),
        "decision_timing":"same-session market close observations set next-session-open target",
        "frozen_profile":"strategy9-e3-research-champion-v1",
    }
    (output/"market-risk-controller-manifest.json").write_text(json.dumps(manifest,indent=2,sort_keys=True)+"\n")
    evidence=sorted(p for p in output.iterdir() if p.is_file() and p.name!="SHA256SUMS.txt")
    (output/"SHA256SUMS.txt").write_text("".join(f"{_sha256(p)}  {p.name}\n" for p in evidence))


def run(output: Path, family: str, params: dict, vix_csv: Path) -> int:
    if family not in SUPPORTED: raise RuntimeError(f"unsupported family {family}")
    if not vix_csv.exists(): raise RuntimeError(f"missing VIX authority: {vix_csv}")
    if os.environ.get("PIT_OFFICIAL_BACKTEST","0") not in ("","0"):
        raise RuntimeError("market-risk research replay requires PIT_OFFICIAL_BACKTEST=0")
    original=closure.build_source
    def build(destination: Path) -> str:
        base=original(destination)
        corrected_text=corrected.install(base)
        return install_market_observations(corrected_text,family,params)
    closure.build_source=build
    os.environ["BEST_EFFORT_SECURITY_TYPES"]=str(corrected.base.DEFAULT_LEDGER.resolve())
    os.environ["BEST_EFFORT_CLASSIFICATION_SCENARIO"]="reviewed_18"
    os.environ["MARKET_RISK_VIX_CSV"]=str(vix_csv.resolve())
    try:
        rc=closure.run(output)
    finally:
        closure.build_source=original
    if rc: return rc
    corrected.base._rewrite_outputs(output.resolve(),"reviewed_18")
    corrected._mark_corrected_outputs(output.resolve())
    _mark_outputs(output.resolve(),family,params,vix_csv.resolve())
    print(f"[MARKET-RISK] family={family} status={STATUS}",flush=True)
    return 0


def main() -> int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--output",type=Path,required=True)
    ap.add_argument("--family",choices=sorted(SUPPORTED),required=True)
    ap.add_argument("--params-json",default="{}")
    ap.add_argument("--vix-csv",type=Path,required=True)
    ap.add_argument("--self-test-source",type=Path)
    args=ap.parse_args()
    params=json.loads(args.params_json)
    if args.self_test_source:
        text=args.self_test_source.read_text()
        out=install_market_observations(text,args.family,params)
        print(json.dumps({"status":"PASS","family":args.family,"generated_sha256":hashlib.sha256(out.encode()).hexdigest()},sort_keys=True))
        return 0
    return run(args.output,args.family,params,args.vix_csv)


if __name__=='__main__':
    raise SystemExit(main())
