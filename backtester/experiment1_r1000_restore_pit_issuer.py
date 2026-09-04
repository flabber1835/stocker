#!/usr/bin/env python3
"""Experiment 1: R1000 baseline with strict-prior SEC CIK issuer-family blocking restored.

Everything else is identical to the completed R1000 correlation-peer baseline:
- same historical IWB membership tape;
- same membership-derived ticker identities;
- same correlation-peer Sentinel breadth;
- same frozen Wealth Core ranking/sizing/exits and LD-RC parameters.
Only Wealth Core issuer-family blocking changes from security-singleton to strict-prior SEC CIK.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

from backtester import run_r1000_correlation_peers as rbase
from backtester import run_r1000_correlation_peers_v2 as v2

LABEL = "EXPERIMENT_1_R1000_RESTORE_PIT_ISSUER"


def transformed_source(output: Path) -> str:
    text = v2.transformed_source(output)
    old = """    def sector_key(tid, ds):
        return f'SID:{sid[tid]}'
    def issuer_key(tid, ds):
        return f'SID:{sid[tid]}'
    actions,split_dates=load_actions(); spy,bil=load_funds(); book=Book(); native=Native()"""
    new = """    spec=importlib.util.spec_from_file_location('experiment1_pit_authority', Path('backtester/experiments/2026-08-27-sector-abc/run.py'))
    if spec is None or spec.loader is None: raise RuntimeError('cannot load PIT authority model')
    pitmod=importlib.util.module_from_spec(spec); spec.loader.exec_module(pitmod)
    pit_model=pitmod.PITFF12(
        Path('research/sentinel-fastgate/pit-evidence/generated/sec_cik_change_events.csv.gz'),
        Path('research/sentinel-fastgate/pit-evidence/generated/sec_sic_submissions.csv.gz'),
        {str(sid[i]):str(tick[i]) for i in range(n)})
    def sector_key(tid, ds):
        return f'SID:{sid[tid]}'
    def issuer_key(tid, ds):
        ticker=str(tick[tid]); session=str(ds)
        cik=pit_model._strict_prior(pit_model.cik_dates.get(ticker,()), pit_model.cik_values.get(ticker,()), session)
        return f'SEC_CIK:{cik}' if cik is not None else f'SEC_UNKNOWN:{sid[tid]}'
    actions,split_dates=load_actions(); spy,bil=load_funds(); book=Book(); native=Native()"""
    if text.count(old) != 1:
        raise RuntimeError(f"issuer seam count={text.count(old)}")
    text = text.replace(old, new, 1)
    return text


def finalize(output: Path, membership_manifest: Path) -> None:
    rbase.base.old.postprocess('fullpit', output)
    rbase.base.finalize('fullpit', output)
    rbase.finalize_experiment(output, membership_manifest)
    summary_path = output / 'summary.json'
    summary = json.loads(summary_path.read_text())
    summary['experiment'] = 'experiment1_r1000_restore_strict_prior_sec_cik_issuer'
    summary['evidence_label'] = LABEL
    summary['domain_changes']['issuer_family'] = 'strict-prior SEC CIK; unknown issuer is security singleton'
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + '\n')
    manifest_path = output / 'r1000-experiment-manifest.json'
    manifest = json.loads(manifest_path.read_text())
    manifest['schema'] = 'backtester.r1000-exp1-pit-issuer/1'
    manifest['evidence_label'] = LABEL
    manifest['experiment'] = summary['experiment']
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\n')
    files=[output/'daily.csv.gz',output/'metrics.csv',summary_path,manifest_path]
    (output/'SHA256SUMS.txt').write_text(''.join(f"{rbase.base.old.sha256(p)}  {p.name}\n" for p in files))


def main() -> int:
    ap=argparse.ArgumentParser()
    ap.add_argument('--membership',type=Path,required=True)
    ap.add_argument('--membership-manifest',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True)
    args=ap.parse_args(); args.output.mkdir(parents=True,exist_ok=True)
    generated=Path('/tmp/r1000_exp1_restore_pit_issuer.py')
    generated.write_text(transformed_source(args.output),encoding='utf-8')
    env=dict(os.environ); env['RESEARCH_REPLAY_MODE']='fullpit'; env['R1000_MEMBERSHIP_SNAPSHOTS']=str(args.membership)
    print(f'[RUN] {LABEL}',flush=True)
    subprocess.run([sys.executable,str(generated)],check=True,env=env)
    finalize(args.output,args.membership_manifest)
    return 0

if __name__=='__main__': raise SystemExit(main())
