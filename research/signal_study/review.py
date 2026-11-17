"""Read-only interpretation and additional audit of the frozen signal probes."""
import argparse
from collections import Counter
import json
from pathlib import Path

import numpy as np

from research.exposure_oracle import inputs

PROFILE_NAMES = ('core_momentum_5','core_volatility_20','core_peak_dd','core_momentum_acceleration',
    'core_vol_acceleration','core_downside20','recorded_stops20','leadership_r5','leadership_r20',
    'leadership_minus_core20','leadership_minus_spy20','damaged_breadth','damaged_breadth_change1')


def clusters(records):
    """Count overlapping outcome windows; never treat daily labels as independent."""
    groups=[]
    for r in sorted(records,key=lambda r:r['t']):
        if groups and r['t']<groups[-1]['end_index']:
            groups[-1]['end_index']=max(groups[-1]['end_index'],r['end_index'])
            groups[-1]['events']+=1
        else:
            groups.append(dict(start=r['session'],start_index=r['t'],end_index=r['end_index'],events=1))
    return groups


def check_scalers(models, features, names):
    for m in models:
        columns=[names.index(k) for k in m['features']]
        train=features[np.ix_(m['train_indices'],columns)]
        variance=np.var(train,axis=0)
        scale=np.sqrt(variance)
        # StandardScaler treats effectively constant columns as scale one.
        eps=np.finfo(float).eps; n=len(train); mean=np.mean(train,axis=0)
        constant=variance<=n*eps*variance+(n*mean*eps)**2
        scale[constant]=1.
        if not np.allclose(scale,m['scale'],rtol=1e-10,atol=1e-12):
            raise ValueError('training-only scale audit failed')
    return len(models)


def review(folder: Path):
    output=folder/'review.json'
    if output.exists(): raise ValueError('review already exists')
    spec=json.loads((folder/'protocol.json').read_text())
    summary=json.loads((folder/'summary.json').read_text())
    if inputs.sha((folder/'protocol.json').read_bytes())!=summary['protocol_sha256']:
        raise ValueError('protocol changed')
    root=Path(__file__).resolve().parents[2]
    for p,expected in spec['sources'].items():
        if inputs.sha((root/p).read_bytes())!=expected: raise ValueError('frozen research source changed: '+p)
    predictions=[json.loads(line) for line in (folder/'predictions.jsonl').read_text().splitlines()]
    models=json.loads((folder/'models.json').read_text())
    rows=[json.loads(line) for line in (folder/'features.jsonl').read_text().splitlines()]
    names=spec['feature_names']; dates=[r['session'] for r in rows]
    x=np.array([[r['values'][k] if r['values'][k] is not None else np.nan for k in names] for r in rows])
    scales=check_scalers(models,x,names)
    paired=[]
    for r in summary['probes']:
        if r['view']!='augmented' or r['tier']=='existing': continue
        b=next(v for v in summary['probes'] if v['view']=='matched_existing' and all(v[k]==r[k] for k in ('tier','task','horizon','model')))
        blocks=[]
        for f,m in r['blocks'].items():
            bm=b['blocks'][f]
            if m['n'] and m['auc'] is not None and bm['auc'] is not None:
                blocks.append(dict(fold=f,n=m['n'],auc_delta=m['auc']-bm['auc']))
        paired.append(dict(**{k:r[k] for k in ('tier','task','horizon','model')},
            n=r['aggregate']['n'],auc_delta=r['aggregate']['auc']-b['aggregate']['auc'],
            blocks=blocks,better_auc_blocks=sum(v['auc_delta']>1e-12 for v in blocks),
            mean_flagged_gain=r['aggregate']['mean_flagged_gain'],
            baseline_mean_flagged_gain=b['aggregate']['mean_flagged_gain']))
    profile=json.loads((folder/'oracle-profiles.json').read_text())
    feature_profiles=[]
    for task,actual in (('exit',1.),('entry',0.)):
        for name in PROFILE_NAMES:
            selected=[r['features'][name] for r in profile if r['actual']==actual and r['features'][name]['value'] is not None]
            if selected:
                values=[r['retrospective_percentile'] for r in selected]
                feature_profiles.append(dict(task=task,feature=name,n=len(values),
                    median_percentile=float(np.median(values)),top_decile=sum(v>=.9 for v in values),
                    bottom_decile=sum(v<=.1 for v in values),median_value=float(np.median([r['value'] for r in selected]))))
    grouped={}
    for r in predictions:
        if r['view']!='augmented': continue
        key=tuple(r[k] for k in ('tier','task','horizon','model'))
        if r['flag']: grouped.setdefault(key,[]).append(dict(r,end_index=dates.index(r['end'])))
    flags=[]
    for key,records in grouped.items():
        positive=[r['gain'] for r in records if r['gain']>0]
        negative=[r['gain'] for r in records if r['gain']<0]
        flags.append(dict(zip(('tier','task','horizon','model'),key),flagged=len(records),
            profitable_events=len(positive),losing_events=len(negative),
            mean_profitable_gain=float(np.mean(positive)) if positive else None,
            mean_losing_gain=float(np.mean(negative)) if negative else None,
            overlapping_clusters=clusters(records),
            flagged_by_year=dict(Counter(r['session'][:4] for r in records))))
    result=dict(status='PASS',source_sha256=inputs.sha(Path(__file__).read_bytes()),
        protocol_sha256=summary['protocol_sha256'],training_scales_verified=scales,
        paired_comparisons=paired,oracle_profiles=feature_profiles,flagged_diagnostics=flags,
        caveat='Post-run descriptions of predeclared probes; no parameter tuning, winner selection, or additive event-return claim.')
    inputs.write_json(output,result)
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--result',type=Path,required=True)
    args=parser.parse_args()
    result=review(args.result)
    print(json.dumps({k:v for k,v in result.items() if k not in ('paired_comparisons','oracle_profiles','flagged_diagnostics')},indent=2))
