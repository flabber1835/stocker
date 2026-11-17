"""Read-only candidate-universe diagnostics; never selects a replacement policy."""
import argparse
import json
from pathlib import Path

import numpy as np
from scipy.stats import spearmanr

from research.exposure_oracle import inputs, accounting
from research.structured_search import data, audit


def review(snapshot: Path, root: Path):
    destination=root/'candidate-review.json'
    if destination.exists(): raise ValueError('candidate review already exists')
    _,rows=inputs.load(snapshot)
    days,initial,_=accounting.tape(rows,canonical=False)
    matrix=data.matrices(days); dates=[r['session'] for r in rows]
    config=json.loads((root/'protocol.json').read_text())
    summary=json.loads((root/'summary.json').read_text())
    selections=json.loads((root/'selections.json').read_text())
    if inputs.sha((root/'protocol.json').read_bytes())!=summary['protocol_sha256']:
        raise ValueError('protocol identity changed')
    if json.loads((snapshot/'manifest.json').read_text())!=config['source_manifest']:
        raise ValueError('review uses a different source snapshot')
    paths=audit.archive(root/'outer-candidates.npz')
    start=config['folds'][0]['left']; initial_index=int(data.action_indices([float(initial)])[0])
    base=summary['metrics']['baseline']; candidates=[]
    for c in config['candidates']:
        p=paths[c['id']]
        metrics=data.window(matrix,p,initial_index,dates,start,len(days))
        gains=[]
        for s in selections:
            f=s['fold']; m=data.window(matrix,p,initial_index,dates,f['left'],f['right'])
            gains.append(float(np.log(m['multiple']/s['outer_metrics']['baseline']['multiple'])))
        candidates.append(dict(**c,metrics=metrics,positive_blocks=sum(g>1e-12 for g in gains),
            block_log_gains=gains,qualifies_economic_pair=metrics['cagr']>base['cagr']+1e-10
            and metrics['maxdd']<=base['maxdd']+1e-10,behavior_sha256=inputs.sha(p[start:].tobytes())))
    eligible=[c for c in candidates if c['qualifies_economic_pair']]
    families={}
    for family in ('state','trend','predictive','combination'):
        members=[c for c in candidates if c['family']==family]
        families[family]=dict(candidates=len(members),distinct_outer_behaviors=len({c['behavior_sha256'] for c in members}),
            higher_cagr_and_no_worse_maxdd=sum(c['qualifies_economic_pair'] for c in members),
            highest_cagr=max(c['metrics']['cagr'] for c in members),
            median_cagr=float(np.median([c['metrics']['cagr'] for c in members])),
            median_maxdd=float(np.median([c['metrics']['maxdd'] for c in members])))
    transfer=[]
    for s in selections:
        f=s['fold']; earlier=[]; later=[]; count=positive=0
        for r in s['records']:
            m=data.window(matrix,paths[r['id']],initial_index,dates,f['left'],f['right'])
            earlier.append(r['metrics']['cagr']); later.append(m['cagr'])
            if (r['metrics']['maxdd']<=s['baseline']['metrics']['maxdd']+1e-10
                    and r['metrics']['cagr']>s['baseline']['metrics']['cagr']+1e-10):
                count+=1
                positive+=int(m['cagr']>s['outer_metrics']['baseline']['cagr']+1e-10 and
                              m['maxdd']<=s['outer_metrics']['baseline']['maxdd']+1e-10)
        transfer.append(dict(fold=f['id'],validation_to_outer_cagr_rank_correlation=float(spearmanr(earlier,later).statistic),
            validation_improvements_within_drawdown=count,also_improve_next_block_within_drawdown=positive))
    result=dict(caveat='Whole-outer rankings are hindsight diagnostics, not promotion selections.',
        source_sha256=inputs.sha(Path(__file__).read_bytes()),protocol_sha256=summary['protocol_sha256'],
        families=families,distinct_behaviors=len({c['behavior_sha256'] for c in candidates}),
        higher_cagr_and_no_worse_maxdd=len(eligible),
        hindsight_highest_cagr=max(candidates,key=lambda c:c['metrics']['cagr']),
        hindsight_top_economic_pair=sorted(eligible,key=lambda c:-c['metrics']['cagr'])[:5],
        transfer=transfer,candidates=candidates)
    inputs.write_json(destination,result)
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot',type=Path,required=True)
    parser.add_argument('--result',type=Path,required=True)
    args=parser.parse_args()
    result=review(args.snapshot,args.result)
    print(json.dumps({k:v for k,v in result.items() if k!='candidates'},indent=2))
