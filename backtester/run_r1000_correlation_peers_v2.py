#!/usr/bin/env python3
"""R1000 correlation-peer replay with membership-derived security identities.

Historical IWB membership is already bound to contemporaneous SEP tickers by
build_r1000_iwb_membership_sep.py. The replay therefore constructs its security
key space directly from the union of those historical ticker episodes and does
not depend on current Sharadar TICKERS metadata for category/listing/issuer/sector.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys

from backtester import run_r1000_correlation_peers as base


def transformed_source(output: Path) -> str:
    text=base.transformed_source(output)
    pattern=r"def load_meta\(\):.*?\n\ndef load_actions\(\):"
    replacement="""def load_meta():
    # R1000 snapshot membership is the historical security/listing authority.
    # Security episodes are intentionally independent ticker-level identities.
    members=sorted(set(_r1000.ticker.astype(str).str.upper()))
    tick=np.array(members,object); tmap={t:i for i,t in enumerate(tick)}
    sid=np.array(['R1000_TICKER:'+t for t in tick],object)
    common=np.ones(len(tick),dtype=bool)
    sector=np.array([None]*len(tick),object)
    exchange=np.array(['']*len(tick),object)
    fp=np.full(len(tick),np.datetime64('1900-01-01'),dtype='datetime64[D]')
    lp=np.full(len(tick),np.datetime64('2100-01-01'),dtype='datetime64[D]')
    issuer=np.array(['SID:'+s for s in sid],object)
    return tick,tmap,sid,common,sector,exchange,fp,lp,issuer


def load_actions():"""
    text=base.replace_regex(text,pattern,replacement,'membership-derived load_meta')

    old="'control_reason':ctl_reason,'A_reason':a_reason,'B_reason':b_reason,'fast_signal':fastsig,'slow_signal':slowsig})"
    new="'control_reason':ctl_reason,'A_reason':a_reason,'B_reason':b_reason,'fast_signal':fastsig,'slow_signal':slowsig,'r1000_membership_count':len(r1000_membership(ds)),'eligible_count':int(len(et)),'leadership_population':int(nk),'held_count':int(len(held))})"
    text=base.base.old.replace_once(text,old,new,'R1000 daily geometry telemetry')
    return text


def main() -> int:
    ap=argparse.ArgumentParser()
    ap.add_argument('--membership',type=Path,required=True)
    ap.add_argument('--membership-manifest',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True)
    args=ap.parse_args(); args.output.mkdir(parents=True,exist_ok=True)
    generated=Path('/tmp/r1000_correlation_peers_v2.py')
    generated.write_text(transformed_source(args.output),encoding='utf-8')
    env=dict(os.environ); env['RESEARCH_REPLAY_MODE']='fullpit'; env['R1000_MEMBERSHIP_SNAPSHOTS']=str(args.membership)
    print('[RUN] BEST_EFFORT_PIT_R1000_CORRELATION_PEERS identity=membership-derived ticker episodes',flush=True)
    subprocess.run([sys.executable,str(generated)],check=True,env=env)
    base.base.old.postprocess('fullpit',args.output)
    base.base.finalize('fullpit',args.output)
    base.finalize_experiment(args.output,args.membership_manifest)
    return 0

if __name__=='__main__': raise SystemExit(main())
