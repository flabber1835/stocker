#!/usr/bin/env python3
"""Leadership-only classification perturbation diagnostics.

RESEARCH / NOT CERTIFIED.

The perturbation is applied after the eligible universe, Wealth Core pool and
stock-selection ranks are fixed. Only the recent-leadership witness is changed.
This isolates classification/universe sensitivity mechanism #2: controller
input contamination through the leadership basket.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd

from backtester import research_champion_market_risk_full_replay as market
from backtester import run_research_champion_pit_closure_20y as closure

STATUS = "RESEARCH / NOT CERTIFIED"
MODES = {
    "baseline",
    "drop_cutoff_1",
    "add_cutoff_1",
    "swap_cutoff_1",
    "drop_cutoff_3",
    "add_cutoff_3",
    "swap_seeded_1",
}


def _once(text: str, old: str, new: str, label: str) -> str:
    n = text.count(old)
    if n != 1:
        raise RuntimeError(f"{label}: expected one source seam, found {n}")
    return text.replace(old, new, 1)


def install_perturbation(text: str, mode: str, seed: int) -> str:
    if mode not in MODES:
        raise RuntimeError(f"unsupported perturbation mode {mode}")
    helper = f'''LEADERSHIP_PERTURB_MODE={mode!r}
LEADERSHIP_PERTURB_SEED={int(seed)}
_LEAD_PERTURB_SESSIONS=0
_LEAD_PERTURB_MEMBERS_CHANGED=0

def _leadership_perturb(ds,et,ordrec,nk,recsel):
    global _LEAD_PERTURB_SESSIONS,_LEAD_PERTURB_MEMBERS_CHANGED
    mode=LEADERSHIP_PERTURB_MODE
    if mode=='baseline' or nk<=0: return recsel
    selected=list(map(int,recsel))
    outsiders=list(map(int,et[ordrec[nk:nk+5]]))
    before=tuple(selected)
    if mode=='drop_cutoff_1':
        if selected: selected=selected[:-1]
    elif mode=='add_cutoff_1':
        selected=selected+outsiders[:1]
    elif mode=='swap_cutoff_1':
        if selected and outsiders: selected=selected[:-1]+outsiders[:1]
    elif mode=='drop_cutoff_3':
        selected=selected[:-min(3,len(selected))] if selected else selected
    elif mode=='add_cutoff_3':
        selected=selected+outsiders[:3]
    elif mode=='swap_seeded_1':
        if selected and outsiders:
            h=int(hashlib.sha256(f'{{ds}}:{{LEADERSHIP_PERTURB_SEED}}:selected'.encode()).hexdigest()[:16],16)
            j=h%len(selected)
            k=int(hashlib.sha256(f'{{ds}}:{{LEADERSHIP_PERTURB_SEED}}:outside'.encode()).hexdigest()[:16],16)%len(outsiders)
            selected[j]=outsiders[k]
    after=tuple(selected)
    if after!=before:
        _LEAD_PERTURB_SESSIONS+=1
        _LEAD_PERTURB_MEMBERS_CHANGED+=len(set(before)^set(after))
    return np.asarray(selected,dtype=np.int32)
'''
    text = _once(text, "def run():\n", helper + "\ndef run():\n", "perturbation helper")
    old = "                ordrec=np.lexsort((sid_et,-recent[et])); recsel=et[ordrec[:nk]]"
    new = old + "\n                recsel=_leadership_perturb(ds,et,ordrec,nk,recsel)"
    text = _once(text, old, new, "leadership selection perturbation")
    marker = "        'leadership_overlap_checks':overlap_checks,"
    replacement = marker + "\n        'leadership_perturbation':{'mode':LEADERSHIP_PERTURB_MODE,'seed':LEADERSHIP_PERTURB_SEED,'sessions_changed':_LEAD_PERTURB_SESSIONS,'membership_symmetric_difference_total':_LEAD_PERTURB_MEMBERS_CHANGED},"
    text = _once(text, marker, replacement, "perturbation summary")
    compile(text, "<research-champion-leadership-perturbation>", "exec")
    return text


def _sha256(path: Path) -> str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''): h.update(chunk)
    return h.hexdigest()


def mark(output: Path, mode: str, seed: int, family: str) -> None:
    daily=output/'daily.csv.gz'
    if daily.exists():
        d=pd.read_csv(daily)
        d['leadership_perturbation_mode']=mode
        d['leadership_perturbation_seed']=seed
        d.to_csv(daily,index=False,compression={'method':'gzip','mtime':0})
    manifest={
        'status':STATUS,
        'scope':'LEADERSHIP_ONLY_AFTER_STOCK_SELECTION_FIXED',
        'mode':mode,
        'seed':seed,
        'controller_family':family,
        'interpretation':'robustness stress test; not a claim about historical truth',
        'mechanism_isolated':'universe/classification -> recent leadership -> LDRC allocation',
    }
    (output/'leadership-perturbation-manifest.json').write_text(json.dumps(manifest,indent=2,sort_keys=True)+'\n')
    evidence=sorted(p for p in output.iterdir() if p.is_file() and p.name!='SHA256SUMS.txt')
    (output/'SHA256SUMS.txt').write_text(''.join(f'{_sha256(p)}  {p.name}\n' for p in evidence))


def run(output: Path, family: str, params: dict, vix_csv: Path, mode: str, seed: int) -> int:
    original=closure.build_source
    closure.build_source=lambda destination: install_perturbation(original(destination),mode,seed)
    try:
        rc=market.run(output,family,params,vix_csv)
    finally:
        closure.build_source=original
    if rc: return rc
    mark(output.resolve(),mode,seed,family)
    print(f"[LEADERSHIP-PERTURB] family={family} mode={mode} seed={seed} status={STATUS}",flush=True)
    return 0


def main() -> int:
    ap=argparse.ArgumentParser()
    ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--family',choices=sorted(market.SUPPORTED),required=True)
    ap.add_argument('--params-json',default='{}')
    ap.add_argument('--vix-csv',type=Path,required=True)
    ap.add_argument('--mode',choices=sorted(MODES),required=True)
    ap.add_argument('--seed',type=int,default=17)
    ap.add_argument('--self-test-source',type=Path)
    args=ap.parse_args(); params=json.loads(args.params_json)
    if args.self_test_source:
        text=install_perturbation(args.self_test_source.read_text(),args.mode,args.seed)
        print(json.dumps({'status':'PASS','mode':args.mode,'seed':args.seed,'sha256':hashlib.sha256(text.encode()).hexdigest()},sort_keys=True))
        return 0
    return run(args.output,args.family,params,args.vix_csv,args.mode,args.seed)

if __name__=='__main__': raise SystemExit(main())
