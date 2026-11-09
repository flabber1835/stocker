"""Hosted 144-profile grid over one authenticated immutable P00 history."""
import argparse
import base64
from fractions import Fraction as Q
import gzip
import hashlib
import json
from pathlib import Path
import time

from p00_sentinel_grid_policy import BASELINE, NO_EXTRA, canary, hosted, need, profiles, parent_module, select, targets
from p00_recovery_hold_worker import load, windows

PERIODS = dict(full=('2018-01-02','2026-07-31'), training=('2018-01-02','2022-12-30'),
               development=('2018-01-02','2020-12-31'), stress_2021_2022=('2021-01-04','2022-12-30'),
               validation_2023_2024=('2023-01-03','2024-12-31'), latest_2025_2026=('2025-01-02','2026-07-31'))


def journal(path):
    with gzip.open(path,'rt') as stream:
        return [json.loads(line) for line in stream]


def exact_frontier(records):
    def point(r): return Q(r['metrics']['multiple']),Q(r['metrics']['maximum_drawdown_magnitude'])
    return sorted(r['id'] for r in records if not any(
        point(other)[0] >= point(r)[0] and point(other)[1] <= point(r)[1] and point(other) != point(r)
        for other in records))


def run(root, out):
    hosted()
    import numpy as np
    import full_system_controller_worker as engine
    started = time.monotonic()
    cp, formation, rows = load(root)
    canaries = canary(Path('/variant/sentinel/controller/champion_frozen.py').read_bytes())
    engine.profiles,engine.parent_module,engine.independent_targets,engine.select = profiles,parent_module,targets,select
    engine.run(root,out,source_review_path=root.parent/'stopped-review/core-review.json',core_identity=cp['sha256'])
    engine.write(out/'constructor-canary.json',canaries)
    source_summary=json.loads((out/'summary.json').read_bytes())
    refs=json.loads(Path('/driver/p00-sentinel-grid-references.json').read_bytes())
    path_records=journal(out/'paths.jsonl.gz')
    codes={v['profile']:np.frombuffer(base64.b64decode(v['path_b64'],validate=True),dtype='uint8') for v in path_records}
    vp=json.loads((out/'value-proof.json').read_bytes());levels=vp['exposure_levels']
    for pid in (BASELINE,NO_EXTRA):
        report=source_summary['reports'][pid]
        need('alias_of' not in report and report['journal'] == refs['profiles'][pid]['direct_journal'],
             'EXACT_PREVIOUS_CONTROL_ACCOUNT_JOURNAL')
        need(report['full'] == refs['profiles'][pid]['full']
             and hashlib.sha256(np.asarray(levels)[codes[pid]].astype('<f8').tobytes()).hexdigest()
                 == refs['profiles'][pid]['measured_target_sha256'], 'EXACT_PREVIOUS_CONTROL_METRICS_AND_TARGETS')
    table=[{} for _ in rows]
    for item in journal(out/'factors.jsonl.gz'):table[item['index']][item['pair']]=item
    grouped={}
    scores=[]
    for profile in profiles():
        pid=profile['id'];code=codes[pid];group=hashlib.sha256(code.tobytes()).hexdigest()
        if group not in grouped:grouped[group]=engine.values(rows,code,table)
        series,turn=grouped[group]
        periods={name:engine.metrics(series,start,end) for name,(start,end) in PERIODS.items()}
        annual={str(y):engine.metrics(series,f'{y}-01-01',max(d for d,_ in series if d[:4]==str(y))) for y in range(2018,2027)}
        scores.append(dict(id=pid,profile=profile,group=group,periods=periods,annual=annual,
                           allocation_changes=int((code[1:-1] != code[:-2]).sum()),
                           turnover=str(sum(turn,Q(0))), close_target_counts={str(level):int((np.asarray(levels)[code]==level).sum()) for level in levels}))
    training=json.loads((out/'training-scores.json').read_bytes())
    locked=json.loads((out/'locked-selection.json').read_bytes())
    frontier=exact_frontier(training)
    wanted=list(dict.fromkeys([BASELINE,NO_EXTRA]+locked['selected']+frontier))
    aligned=[]
    for first,last,complete in windows(rows):
        aligned.append(dict(anchor=rows[first]['session'],end=rows[last]['session'],complete=complete,
                            profiles={pid:engine.metrics(grouped[hashlib.sha256(codes[pid].tobytes()).hexdigest()][0],
                                      rows[first+1]['session'],rows[last]['session']) for pid in wanted}))
    engine.write(out/'all-grid-scores.json',scores)
    engine.write(out/'grid-summary.json',dict(status='P00_SENTINEL_GRID_REVIEW_REQUIRED',profiles=144,
        unique_paths=len(grouped),selection=locked,training_frontier=frontier,
        original_defensive_windows=aligned,controls_exact_to_previous_admitted_experiment=True,
        canonical_core_transitions=0,original_core_backtests_resumed=False,known_history_not_unseen=True,
        elapsed_seconds=time.monotonic()-started,production_contacted=False))


def review(root,evidence,out):
    hosted()
    from p00_sentinel_grid_review import review as independent
    independent(root,evidence,out)


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--evidence',type=Path)
    parser.add_argument('--mode',choices=('worker','review'),required=True)
    args=parser.parse_args()
    if args.mode=='review':review(args.root,args.evidence,args.output)
    else:run(args.root,args.output)
