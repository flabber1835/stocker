"""Reuse the SHA-pinned replay driver with explicit round-2 source and reference seams."""
import hashlib
import json
import os
from pathlib import Path
from round2_arms import V1, SOURCE_SHA, BASELINE_RESULT, VARIANTS
from treatments import replace_once

DRIVER_SHA='600de866742407f9ad953f09ed4185a1e7987eefc21d473ff63b242fb521c872'
REFERENCE_RUN='34441488484'
REFERENCE_HEAD='8d03d04c0787ddd9b1bed7ecef58183f22288a47'


def verify_artifact(root, variant, run_id, head, source_sha):
    root=root.resolve()
    checks=json.loads((root/'SHA256.json').read_text())
    for relative,expected in checks.items():
        p=(root/relative).resolve()
        if not p.is_relative_to(root):raise RuntimeError('artifact path escapes root')
        if hashlib.sha256(p.read_bytes()).hexdigest()!=expected:raise RuntimeError('artifact checksum mismatch: '+relative)
    for key in ('RESULT.json','engine/daily.csv','engine/transactions.csv','engine/close-decisions.csv','generated.py'):
        if key not in checks:raise RuntimeError('missing artifact checksum: '+key)
    result=json.loads((root/'RESULT.json').read_text())
    if (result['status']!='PASS_FRESH_CAUSAL_PIT_REPLAY' or result['variant']!=variant
        or str(result['source']['run_id'])!=str(run_id) or result['source']['experiment_head']!=head
        or result['source']['candidate_sha256']!=source_sha
        or hashlib.sha256((root/'generated.py').read_bytes()).hexdigest()!=source_sha):
        raise RuntimeError('artifact authority mismatch')
    from run_experiment import DATASET_SHA, CORE_SHA, TX_SHA, CLOSE_SHA, ECONOMIC_COLUMNS, frame_hash
    import pandas as pd
    if (result['dataset_sha256']!=DATASET_SHA or result['core_full_sha256']!=CORE_SHA
        or result['transactions_sha256']!=TX_SHA or result['close_decisions_sha256']!=CLOSE_SHA):
        raise RuntimeError('artifact Core authority mismatch')
    frame=pd.read_csv(root/'engine/daily.csv',parse_dates=['date'])
    if frame_hash(frame,ECONOMIC_COLUMNS)!=result['core_economic_sha256']:raise RuntimeError('artifact Core tape mismatch')
    return result


def verify_reference(root):
    r=verify_artifact(root,'candidate',REFERENCE_RUN,REFERENCE_HEAD,SOURCE_SHA)
    if r!=BASELINE_RESULT:raise RuntimeError('reference result differs from committed manifest')
    return r


def driver():
    source=(V1/'run_experiment.py').read_text()
    if hashlib.sha256(source.encode()).hexdigest()!=DRIVER_SHA:raise RuntimeError('pinned driver changed')
    source=replace_once(source,'from treatments import VARIANTS, SOURCE_SHA, build',
        'from round2_arms import VARIANTS, SOURCE_SHA, build, EXACT_ARMS, BREADTH_ARMS, BASELINE_RESULT\nfrom run_round2 import verify_reference')
    source=replace_once(source,'research-budget/simplification-v1/slot-','research-budget/simplification-v2/slot-')
    source=replace_once(source,"    args=ap.parse_args();out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)",
        "    ap.add_argument('--reference',type=Path,required=True)\n"
        "    args=ap.parse_args();prior=verify_reference(args.reference)\n"
        "    out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)")
    source=replace_once(source,"args.variant not in ('no_peers','combined')",'args.variant not in BREADTH_ARMS')
    start=source.index("    if args.variant=='baseline':\n        if counts!=")
    end=source.index("    elif args.variant in ('selective_peers','bounded_counters'):",start)
    source=source[:start]+'''    if args.variant=='baseline':
        for filename in ('daily.csv','transactions.csv','close-decisions.csv'):
            if (engine/filename).read_bytes()!=(args.reference/'engine'/filename).read_bytes():
                raise RuntimeError('fresh baseline differs from retained candidate: '+filename)
        if counts!=prior['allocation_counts'] or transitions!=prior['transitions']:
            raise RuntimeError('fresh baseline topology mismatch')
        if summary['candidate_A_episodes']!=prior['episodes'] or summary['candidate_A_concordance_releases']!=prior['cross_surface_releases']:
            raise RuntimeError('fresh baseline episode mismatch')
        if windows!=prior['windows']:
            raise RuntimeError('fresh baseline metrics mismatch')
'''+source[end:]
    source=replace_once(source,"args.variant in ('selective_peers','bounded_counters')",'args.variant in EXACT_ARMS')
    source=replace_once(source,"'schema':'research.v5-ex3-v6-simplification/1'","'schema':'research.v5-ex3-v6-simplification/2'")
    compile(source,'round2-driver.py','exec')
    return source


if __name__=='__main__':
    p=Path(os.environ['GITHUB_WORKSPACE'])/'round2-driver.py';p.write_text(driver())
    exec(compile(p.read_text(),str(p),'exec'),{'__name__':'__main__','__file__':str(p)})
