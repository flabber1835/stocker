#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'wealth-core-v1-virtual-slot-v1'))
from virtual_patch import CONTROL_NORMALIZED_AST_SHA256, CONTROL_SOURCE_SHA256, DATASET_SHA256, patch_source, sha

VARIANT = 'virtual-slot-free-cash'
FREE_CASH_SOURCE_SHA256 = '740d353a223ab63112d5fb9c6eed1e6d7f8e69b1a6d2f46b83773df8f49daba6'
FREE_CASH_DAILY_SHA256 = 'bf1ecdc2917de2122904be2bb94b246d06e2a6927ad262a843333ee9d91823d1'
FREE_CASH_SUMMARY_SHA256 = '753943497976027746b130d3afbe8365765800ab15d7284f993c3319bcbc984a'
MICRO_FRACTION = 0.01


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def replace_once(text: str, old: str, new: str, label: str) -> str:
    n = text.count(old)
    if n != 1:
        raise RuntimeError(f'{label}: expected one source seam, found {n}')
    return text.replace(old, new, 1)


def audit_patch(source: str) -> str:
    out = source
    out = replace_once(out,
        "    rows=[]; overlap_checks={}; buys=sells=split_events=div_events=0; virtual_entries=virtual_releases=virtual_terminal_releases=virtual_stock_deliveries=virtual_decisions=virtual_gap_promotions=real_micro_executions=0; virtual_cash_locked_peak=0.0",
        "    rows=[]; overlap_checks={}; buys=sells=split_events=div_events=0; virtual_entries=virtual_releases=virtual_terminal_releases=virtual_stock_deliveries=virtual_decisions=virtual_gap_promotions=real_micro_executions=0; virtual_cash_locked_peak=0.0\n    _position_audit=[]; _trade_audit=[]",
        'audit state')

    out = replace_once(out,
        "                    _old_tid=s.tid; book.terminal_pending.pop(_old_tid,None)\n                    if not s.virtual: book.cash+=float(_econ['cash'])\n                    if _kind in ('WRITE_OFF','CASH_MERGER') or int(_econ['delivered_shares'])<=0:",
        "                    _old_tid=s.tid; book.terminal_pending.pop(_old_tid,None)\n                    if not s.virtual:\n                        _trade_audit.append({'date':ds,'gday':int(gday),'slot_index':int(next(i for i,x in enumerate(book.slots) if x is s)),'event':'TERMINAL_EXIT' if (_kind in ('WRITE_OFF','CASH_MERGER') or int(_econ['delivered_shares'])<=0) else 'CORPORATE_ACTION','security_id':str(sid[int(_old_tid)]),'ticker':str(tick[int(_old_tid)]),'qty':float(s.qty),'price':None,'gross_value':float(_econ['cash']),'portfolio_weight':None,'reason':str(_kind),'entry_day_index':int(s.entry_day),'entry_funding_fraction':None,'delivered_security_id':str(getattr(_term,'delivered_security_id',None)) if not (_kind in ('WRITE_OFF','CASH_MERGER') or int(_econ['delivered_shares'])<=0) else None})\n                    if not s.virtual: book.cash+=float(_econ['cash'])\n                    if _kind in ('WRITE_OFF','CASH_MERGER') or int(_econ['delivered_shares'])<=0:",
        'exact terminal audit')

    out = replace_once(out,
        "                elif finite(clraw[s.tid]) and clraw[s.tid]>0 and finite(volume[s.tid]) and volume[s.tid]>0:\n                    _tid=s.tid; book.cash+=(float(s.virtual_cash) if s.virtual else s.qty*float(clraw[_tid])); virtual_terminal_releases+=int(s.virtual); book.sec_ready[_tid]=gday+COOLDOWN",
        "                elif finite(clraw[s.tid]) and clraw[s.tid]>0 and finite(volume[s.tid]) and volume[s.tid]>0:\n                    _tid=s.tid\n                    if not s.virtual: _trade_audit.append({'date':ds,'gday':int(gday),'slot_index':int(next(i for i,x in enumerate(book.slots) if x is s)),'event':'TERMINAL_EXIT','security_id':str(sid[int(_tid)]),'ticker':str(tick[int(_tid)]),'qty':float(s.qty),'price':float(clraw[_tid]),'gross_value':float(s.qty)*float(clraw[_tid]),'portfolio_weight':None,'reason':'TERMINAL_FALLBACK_MARK','entry_day_index':int(s.entry_day),'entry_funding_fraction':None,'delivered_security_id':None})\n                    book.cash+=(float(s.virtual_cash) if s.virtual else s.qty*float(clraw[_tid])); virtual_terminal_releases+=int(s.virtual); book.sec_ready[_tid]=gday+COOLDOWN",
        'fallback terminal audit')

    out = replace_once(out,
        "                    else:\n                        book.cash+=s.qty*float(px)*(1-COST); sells+=1\n                    if s.sell_reason=='stop': stop_days.append(gday)",
        "                    else:\n                        _trade_audit.append({'date':ds,'gday':int(gday),'slot_index':int(next(i for i,x in enumerate(book.slots) if x is s)),'event':'SELL','security_id':str(sid[int(s.tid)]),'ticker':str(tick[int(s.tid)]),'qty':float(s.qty),'price':float(px),'gross_value':float(s.qty)*float(px),'portfolio_weight':(float(s.qty)*float(px)/float(open_eq) if open_eq>0 else None),'reason':str(s.sell_reason),'entry_day_index':int(s.entry_day),'entry_funding_fraction':None,'delivered_security_id':None})\n                        book.cash+=s.qty*float(px)*(1-COST); sells+=1\n                    if s.sell_reason=='stop': stop_days.append(gday)",
        'normal sell audit')

    out = replace_once(out,
        "                        else:\n                            real_micro_executions+=int(_actual_fraction<0.01); book.cash-=q*float(px)*(1+COST); s.tid=tid; s.qty=float(q); s.entry_day=gday; s.reviewed=False; s.pending_sell=False; s.sell_reason=''; s.entry_sig=float(opsig[tid]) if finite(opsig[tid]) and opsig[tid]>0 else np.nan; s.peak=np.nan; book.initialized=True; buys+=1",
        "                        else:\n                            real_micro_executions+=int(_actual_fraction<0.01); _trade_audit.append({'date':ds,'gday':int(gday),'slot_index':int(next(i for i,x in enumerate(book.slots) if x is s)),'event':'BUY','security_id':str(sid[int(tid)]),'ticker':str(tick[int(tid)]),'qty':float(q),'price':float(px),'gross_value':float(q)*float(px),'portfolio_weight':(float(q)*float(px)/float(open_eq) if open_eq>0 else None),'reason':'entry','entry_day_index':int(gday),'entry_funding_fraction':float(_actual_fraction),'delivered_security_id':None}); book.cash-=q*float(px)*(1+COST); s.tid=tid; s.qty=float(q); s.entry_day=gday; s.reviewed=False; s.pending_sell=False; s.sell_reason=''; s.entry_sig=float(opsig[tid]) if finite(opsig[tid]) and opsig[tid]>0 else np.nan; s.peak=np.nan; book.initialized=True; buys+=1",
        'real buy audit')

    out = replace_once(out,
        "                book.cash+=(float(_slot.virtual_cash) if _slot.virtual else _slot.qty*float(_px)); virtual_terminal_releases+=int(_slot.virtual); book.sec_ready[_tid]=gday+COOLDOWN; book.terminal_pending.pop(_tid,None)",
        "                if not _slot.virtual: _trade_audit.append({'date':ds,'gday':int(gday),'slot_index':int(next(i for i,x in enumerate(book.slots) if x is _slot)),'event':'TERMINAL_EXIT','security_id':str(sid[int(_tid)]),'ticker':str(tick[int(_tid)]),'qty':float(_slot.qty),'price':float(_px),'gross_value':float(_slot.qty)*float(_px),'portfolio_weight':None,'reason':'TERMINAL_C1_STALE_MARK','entry_day_index':int(_slot.entry_day),'entry_funding_fraction':None,'delivered_security_id':None})\n                book.cash+=(float(_slot.virtual_cash) if _slot.virtual else _slot.qty*float(_px)); virtual_terminal_releases+=int(_slot.virtual); book.sec_ready[_tid]=gday+COOLDOWN; book.terminal_pending.pop(_tid,None)",
        'C1 audit')

    out = replace_once(out,
        "            shadow_dates.append(date); shadow_eq.append(eq); damaged_hist.append(dam_b)",
        "            for _audit_slot_index,_audit_s in enumerate(book.slots):\n                if not (_audit_s.held() and not _audit_s.virtual): continue\n                _audit_tid=int(_audit_s.tid); _audit_px=float(clraw[_audit_tid]) if finite(clraw[_audit_tid]) else float('nan')\n                if not (finite(_audit_px) and _audit_px>0): continue\n                _audit_value=float(_audit_s.qty)*_audit_px\n                _position_audit.append({'date':ds,'gday':int(gday),'slot_index':int(_audit_slot_index),'entry_day_index':int(_audit_s.entry_day),'security_id':str(sid[_audit_tid]),'ticker':str(tick[_audit_tid]),'qty':float(_audit_s.qty),'close_raw':_audit_px,'position_value':_audit_value,'portfolio_weight':(_audit_value/float(eq) if eq>0 else None),'pending_sell':bool(_audit_s.pending_sell),'pending_sell_reason':str(_audit_s.sell_reason)})\n            shadow_dates.append(date); shadow_eq.append(eq); damaged_hist.append(dam_b)",
        'daily position snapshots')

    out = replace_once(out,
        "    out=pd.DataFrame(rows)\n    out.to_csv(OUT/'daily.csv',index=False)",
        "    pd.DataFrame(_position_audit).to_csv(OUT/'position_snapshots.csv',index=False)\n    pd.DataFrame(_trade_audit).to_csv(OUT/'trade_events.csv',index=False)\n    out=pd.DataFrame(rows)\n    out.to_csv(OUT/'daily.csv',index=False)",
        'audit evidence outputs')

    required = ['position_snapshots.csv', 'trade_events.csv', "'entry_funding_fraction':float(_actual_fraction)"]
    missing = [x for x in required if x not in out]
    if missing: raise RuntimeError(f'audit instrumentation incomplete: {missing}')
    compile(out, '<wealth-core-position-audit>', 'exec')
    return out


def build_episodes(snapshots: pd.DataFrame, events: pd.DataFrame, last_session: str) -> pd.DataFrame:
    if snapshots.empty: raise RuntimeError('no real-position snapshots')
    snapshots = snapshots.copy(); snapshots['date'] = pd.to_datetime(snapshots['date'])
    events = events.copy()
    if not events.empty: events['date'] = pd.to_datetime(events['date'])
    rows=[]
    for (slot_index, entry_day_index), g in snapshots.groupby(['slot_index','entry_day_index'], sort=True):
        g=g.sort_values(['gday','date']); ids=list(dict.fromkeys(g.security_id.astype(str))); tickers=list(dict.fromkeys(g.ticker.astype(str)))
        buys=events[(events.slot_index==slot_index)&(events.entry_day_index==entry_day_index)&(events.event=='BUY')] if not events.empty else pd.DataFrame()
        exits=events[(events.slot_index==slot_index)&(events.entry_day_index==entry_day_index)&(events.event.isin(['SELL','TERMINAL_EXIT']))] if not events.empty else pd.DataFrame()
        buy=buys.sort_values(['gday','date']).iloc[0] if not buys.empty else None; ex=exits.sort_values(['gday','date']).iloc[-1] if not exits.empty else None
        first=g.iloc[0]; final=g.iloc[-1]; minv=g.loc[g.position_value.astype(float).idxmin()]; maxv=g.loc[g.position_value.astype(float).idxmax()]; minw=g.loc[g.portfolio_weight.astype(float).idxmin()]; maxw=g.loc[g.portfolio_weight.astype(float).idxmax()]
        rows.append({'slot_index':int(slot_index),'entry_day_index':int(entry_day_index),'security_ids':'|'.join(ids),'tickers':'|'.join(tickers),'entry_date':str((buy['date'] if buy is not None else first['date']).date()),'exit_date':str(ex['date'].date()) if ex is not None else '','status':'CLOSED' if ex is not None else ('OPEN_AT_END' if str(final['date'].date())==last_session else 'UNRESOLVED_AUDIT_EXIT'),'entry_qty':float(buy['qty']) if buy is not None else float(first['qty']),'entry_price':float(buy['price']) if buy is not None and pd.notna(buy['price']) else float(first['close_raw']),'entry_gross_value':float(buy['gross_value']) if buy is not None else float(first['position_value']),'entry_portfolio_weight':float(buy['portfolio_weight']) if buy is not None and pd.notna(buy['portfolio_weight']) else float(first['portfolio_weight']),'entry_funding_fraction':float(buy['entry_funding_fraction']) if buy is not None and pd.notna(buy['entry_funding_fraction']) else np.nan,'min_value':float(minv.position_value),'min_value_date':str(minv.date.date()),'max_value':float(maxv.position_value),'max_value_date':str(maxv.date.date()),'min_weight':float(minw.portfolio_weight),'min_weight_date':str(minw.date.date()),'max_weight':float(maxw.portfolio_weight),'max_weight_date':str(maxw.date.date()),'final_value':float(final.position_value),'final_weight':float(final.portfolio_weight),'final_qty':float(final.qty),'exit_reason':str(ex['reason']) if ex is not None else '','observed_sessions':int(len(g))})
    return pd.DataFrame(rows).sort_values(['entry_date','slot_index','entry_day_index']).reset_index(drop=True)


def main() -> int:
    ap=argparse.ArgumentParser(); ap.add_argument('--candidate-root',required=True,type=Path); ap.add_argument('--engine',required=True,type=Path); ap.add_argument('--output',required=True,type=Path); args=ap.parse_args()
    from backtester import champion_full_classification_control as control
    from backtester.production_equivalent_economic_overlay import install, assert_contract, assert_one_session_dividend_lag
    from backtester.champion_economic_prefix_audit import normalized_ast
    engine=args.engine.resolve(); output=args.output.resolve(); engine.mkdir(parents=True,exist_ok=True); output.mkdir(parents=True,exist_ok=True)
    manifest=json.loads((Path(os.environ['CANONICAL_PIT_DATASET'])/'manifest.json').read_text())
    if manifest.get('dataset_hash')!=DATASET_SHA256: raise RuntimeError('canonical PIT dataset mismatch')
    _,_,prior=control.build_source(engine,args.candidate_root.resolve()); v1=install(prior); assert_contract(v1)
    if assert_one_session_dividend_lag(v1)!=1: raise RuntimeError('baseline dividend semantics mismatch')
    if sha(v1.encode())!=CONTROL_SOURCE_SHA256: raise RuntimeError(f'V1 source mismatch: {sha(v1.encode())}')
    if sha(normalized_ast(v1).encode())!=CONTROL_NORMALIZED_AST_SHA256: raise RuntimeError('V1 AST mismatch')
    free=patch_source(v1,VARIANT); assert_contract(free)
    if assert_one_session_dividend_lag(free)!=1: raise RuntimeError('free-cash dividend semantics mismatch')
    if sha(free.encode())!=FREE_CASH_SOURCE_SHA256: raise RuntimeError(f'free-cash source mismatch: {sha(free.encode())}')
    audited=audit_patch(free); audited_path=output/'wealth-core-virtual-slot-free-cash-audited.py'; audited_path.write_text(audited); subprocess.run([sys.executable,'-m','py_compile',str(audited_path)],check=True)
    for stale in engine.glob('*'):
        if stale.is_file(): stale.unlink()
    env=os.environ.copy(); env['RESEARCH_REPLAY_MODE']='fullpit'; subprocess.run([sys.executable,str(audited_path)],cwd=Path.cwd(),env=env,check=True)
    daily_path=engine/'daily.csv'; summary_path=engine/'summary.json'
    if file_sha(daily_path)!=FREE_CASH_DAILY_SHA256: raise RuntimeError(f'economic daily witness changed: {file_sha(daily_path)}')
    if file_sha(summary_path)!=FREE_CASH_SUMMARY_SHA256: raise RuntimeError(f'economic summary witness changed: {file_sha(summary_path)}')
    summary=json.loads(summary_path.read_text()); telemetry=summary.get('wealth_core_virtual_slot_experiment') or {}
    if telemetry.get('real_micro_executions')!=0: raise RuntimeError(f'real microscopic execution survived: {telemetry}')
    snapshots=pd.read_csv(engine/'position_snapshots.csv'); events=pd.read_csv(engine/'trade_events.csv'); episodes=build_episodes(snapshots,events,'2026-07-31'); real_buys=events[events.event=='BUY'].copy()
    if real_buys.empty: raise RuntimeError('no real buys recorded')
    min_funding=float(real_buys.entry_funding_fraction.astype(float).min())
    if min_funding<MICRO_FRACTION-1e-12: raise RuntimeError(f'real buy below frozen micro floor: {min_funding}')
    unresolved=episodes[episodes.status=='UNRESOLVED_AUDIT_EXIT']
    if not unresolved.empty: raise RuntimeError(f'unresolved episode exits: {len(unresolved)}')
    episodes.to_csv(output/'position_episodes.csv',index=False); shutil.copy2(engine/'position_snapshots.csv',output/'position_snapshots.csv'); shutil.copy2(engine/'trade_events.csv',output/'trade_events.csv'); shutil.copy2(daily_path,output/'daily.csv'); shutil.copy2(summary_path,output/'summary.json')
    audit_summary={'schema':'research.wealth-core-v1-virtual-slot-position-audit/1','status':'PASS','economic_scope':'WEALTH_CORE_ONLY','variant':VARIANT,'sentinel_metrics_used':False,'source_commit':'23c47f32c8f2174c7fb51b24a825d112fcf323d9','free_cash_source_sha256':FREE_CASH_SOURCE_SHA256,'audited_source_sha256':sha(audited.encode()),'daily_sha256':file_sha(daily_path),'summary_sha256':file_sha(summary_path),'economics_byte_identical_to_completed_run':True,'micro_fraction':MICRO_FRACTION,'real_micro_executions':int(telemetry['real_micro_executions']),'real_buy_events':int(len(real_buys)),'position_episodes':int(len(episodes)),'closed_episodes':int((episodes.status=='CLOSED').sum()),'open_at_end_episodes':int((episodes.status=='OPEN_AT_END').sum()),'minimum_real_entry_funding_fraction':min_funding,'minimum_observed_real_position_weight':float(snapshots.portfolio_weight.astype(float).min()),'maximum_observed_real_position_weight':float(snapshots.portfolio_weight.astype(float).max()),'minimum_observed_real_position_value':float(snapshots.position_value.astype(float).min()),'maximum_observed_real_position_value':float(snapshots.position_value.astype(float).max()),'note':'Observed position weight may fall below 1% after entry because of price movement; the prohibited defect is a real entry below 1% of intended entry capital.'}
    (output/'AUDIT_SUMMARY.json').write_text(json.dumps(audit_summary,indent=2,sort_keys=True)+'\n'); (output/'SHA256.json').write_text(json.dumps({p.name:file_sha(p) for p in sorted(output.iterdir()) if p.is_file() and p.name!='SHA256.json'},indent=2,sort_keys=True)+'\n'); print('[WEALTH_CORE_POSITION_AUDIT] '+json.dumps(audit_summary,sort_keys=True),flush=True); return 0

if __name__=='__main__': raise SystemExit(main())
