"""One user-authorized combined treatment, composed from validated transformations."""
import ast
import hashlib
import json
from pathlib import Path
from treatments import build as build_arm, scope, replace_once, assert_scope, oracle, SOURCE_SHA

VARIANTS=('candidate',)
BASELINE_HEAD='f769623e86e949c35a0ddf7dc7df29744c298eae'
BASELINE_RUN='34436432038'
DRIVER_SHA='600de866742407f9ad953f09ed4185a1e7987eefc21d473ff63b242fb521c872'
HERE=Path(__file__).resolve().parent


def build(variant='candidate'):
    if variant!='candidate': raise ValueError(variant)
    source=build_arm('bounded_counters')
    source=scope(source,'Native',lambda s:replace_once(s,'if self.ramp_idx>=2:','if self.ramp_idx>=1:'))
    source=scope(source,'CandidateA',lambda s:replace_once(s,
        '        vre=finite(spy20) and spy20>LDRC_V','        vre=False'))
    peer_source=build_arm('selective_peers')
    node=next(n for n in ast.parse(peer_source).body if getattr(n,'name',None)=='dynamic_peer_breadth')
    peer=''.join(peer_source.splitlines(keepends=True)[node.lineno-1:node.end_lineno])
    source=scope(source,'dynamic_peer_breadth',lambda _:peer)
    assert_scope(oracle(),source,{'Native','CandidateA','dynamic_peer_breadth'})
    compile(source,'combined-candidate.py','exec')
    return source


def verify_baseline(root):
    checks=json.loads((root/'SHA256.json').read_text())
    for relative,expected in checks.items():
        path=(root/relative).resolve()
        if not path.is_relative_to(root.resolve()): raise RuntimeError('invalid baseline checksum path')
        if hashlib.sha256(path.read_bytes()).hexdigest()!=expected:
            raise RuntimeError('baseline artifact checksum mismatch: '+relative)
    for key in ('RESULT.json','engine/daily.csv','generated.py'):
        if key not in checks: raise RuntimeError('missing baseline checksum: '+key)
    r=json.loads((root/'RESULT.json').read_text())
    from run_experiment import DATASET_SHA, CORE_SHA, TX_SHA, CLOSE_SHA, frame_hash, ECONOMIC_COLUMNS
    import pandas as pd
    if (r['variant']!='baseline' or r['status']!='PASS_FRESH_CAUSAL_PIT_REPLAY'
        or r['source']['experiment_head']!=BASELINE_HEAD or r['source']['run_id']!=BASELINE_RUN
        or r['source']['candidate_sha256']!=SOURCE_SHA or r['dataset_sha256']!=DATASET_SHA
        or r['core_full_sha256']!=CORE_SHA or r['transactions_sha256']!=TX_SHA
        or r['close_decisions_sha256']!=CLOSE_SHA): raise RuntimeError('baseline authority mismatch')
    if hashlib.sha256((root/'generated.py').read_bytes()).hexdigest()!=SOURCE_SHA:
        raise RuntimeError('baseline generated source mismatch')
    frame=pd.read_csv(root/'engine/daily.csv',parse_dates=['date'])
    if frame_hash(frame,ECONOMIC_COLUMNS)!=r['core_economic_sha256']: raise RuntimeError('baseline economic tape mismatch')
    return r


def driver():
    source=(HERE/'run_experiment.py').read_text()
    if hashlib.sha256(source.encode()).hexdigest()!=DRIVER_SHA: raise RuntimeError('frozen replay driver changed')
    edits=[('from treatments import VARIANTS, SOURCE_SHA, build',
            'from candidate_followup import VARIANTS, SOURCE_SHA, build, BASELINE_HEAD, verify_baseline'),
           ('research-budget/simplification-v1/slot-', 'research-budget/simplification-candidate-v1/slot-'),
           ("        baseline=json.loads((args.baseline/'RESULT.json').read_text())",'        baseline=verify_baseline(args.baseline)'),
           ("baseline['source']['experiment_head']!=os.environ['GITHUB_SHA']", "baseline['source']['experiment_head']!=BASELINE_HEAD"),
           ("'experiment_budget':10", "'experiment_budget':1"),
           ("Slot {result['experiment_slot']}/10", "Additional slot {result['experiment_slot']}/1")]
    for old,new in edits: source=replace_once(source,old,new)
    compile(source,'followup-driver.py','exec')
    return source


if __name__=='__main__':
    import os
    p=Path(os.environ['GITHUB_WORKSPACE'])/'followup-driver.py'
    p.write_text(driver())
    exec(compile(p.read_text(),str(p),'exec'),{'__name__':'__main__','__file__':str(p)})
