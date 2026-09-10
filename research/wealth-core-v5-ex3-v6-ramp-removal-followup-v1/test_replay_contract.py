"""Small accounting-clock and evidence-pipeline falsifiers; no Core start."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import types

import numpy as np
import pandas as pd

import ablation_reference as ref
import publish
import run_experiment as run
import variants as v


def main():
    sources=v.build_sources()
    dates=pd.bdate_range('2020-01-01',periods=260)
    rows=[]
    for i,date in enumerate(dates):
        bad=i%70<30
        close=100*np.exp(.001*i+.1*np.sin(i/30))
        rows.append(dict(date=date,measured=i>=10,dd=-.2 if bad else -.03,
                         r5=-.08,r10=-.11,r20=-.08 if bad else .04,r40=-.1 if bad else .02,
                         dam=.95 if bad else .3,green=.05 if bad else .5,ddam5=.35,spy20=.04,
                         volacc=.08,stops20=4 if bad else 0,nav=close,open_eq=close/1.004,
                         close_eq=close,recent_r20=-.1 if bad else .05,recent_r40=-.05))
    obs=pd.DataFrame(rows)
    bil=pd.DataFrame(dict(gap_factor=np.full(len(dates),1.00003),intraday_factor=np.full(len(dates),1.00002)),index=dates)
    env={'COST':.001}
    for name in ('bil_factors','apply_overlay'):
        exec(v.segment(sources['original'],name),env)
    module=types.SimpleNamespace(apply_overlay=env['apply_overlay'],load_funds=lambda:(None,bil))
    frames={}; checkpoints=0
    for name,source in sources.items():
        pure=v.pure(source); ncls,ccls=pure['Native'],pure['CandidateA']
        expected=ref.replay_controller(module,obs,ncls,ccls)
        actual,audit=run.replay(module,obs,ncls,ccls)
        run.require_pair(actual,expected)
        frames[name]=actual
        if name.startswith('compact'):
            restarted,ra=run.replay(module,obs,ncls,ccls,restart=True)
            run.require_pair(actual,restarted)
            assert (audit['episodes'],audit['concordance_releases'])==(ra['episodes'],ra['concordance_releases'])
            checkpoints+=ra['restarts']
    for parent in ('original','simplified'):
        run.require_pair(frames[parent+'_no_ramp'],frames['compact_'+parent+'_no_ramp'])
    # A future observation must not alter any prior output (including the accounting clock).
    changed=obs.copy(); changed.loc[200:,'dd']=-.9; changed.loc[200:,'recent_r20']=-.9
    e=v.pure(sources['compact_original_no_ramp'])
    prefix,_=run.replay(module,changed,e['Native'],e['CandidateA'])
    mask=frames['compact_original_no_ramp'].date<dates[200]
    run.require_pair(frames['compact_original_no_ramp'].loc[mask],prefix.loc[mask])
    # Reordering current-close decisions into current-session allocation must be detectable.
    a=frames['original']; mutant=a.copy(); mutant['allocation']=mutant.close_desired
    try: run.require_pair(a,mutant)
    except AssertionError: pass
    else: raise AssertionError('same-session exposure mutant survived')
    # Check incomplete reporting and lossless tape storage independently of external APIs.
    with tempfile.TemporaryDirectory() as temp:
        root=Path(temp)/'input'; root.mkdir()
        case=root/'baseline'; case.mkdir()
        os.environ.setdefault('GITHUB_RUN_ID','synthetic-contract-check')
        os.environ.setdefault('GITHUB_SHA','synthetic-contract-check')
        receipt=dict(case='baseline',slot=1)
        run.write_json(case/'SLOT.json',receipt)
        combined=pd.DataFrame({'date':a.date})
        tracks={}
        for name,frame in frames.items():
            combined[name+'_allocation']=frame.allocation; combined[name+'_nav']=frame.nav
            # Fixed fixture metrics test formatting/gates; never published as research results.
            metrics={str(y):dict(cagr=.2,max_drawdown=-.2,ending_multiple=2.,sharpe_daily_252=1.) for y in (5,10,15,20)}
            tracks[name]={'metrics':metrics}
        combined.to_csv(case/'daily-tracks.csv',index=False)
        obs.to_csv(case/'observations.csv',index=False)
        run.write_json(case/'RESULT.json',dict(status='PASS',case='baseline',tracks=tracks))
        run.write_json(case/'SHA256.json',{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in case.iterdir()})
        result=publish.build_report(root,Path(temp)/'out')
        assert result['status']=='INCOMPLETE' and len(result['missing_cases'])==6
        assert result['robustness']['original_no_ramp']['original']['formal_screen'] is None
        import gzip
        assert gzip.decompress((Path(temp)/'out/cases/baseline/observations.csv.gz').read_bytes())==(case/'observations.csv').read_bytes()
        # An allocation drift on the final session cannot be described as terminal reconvergence.
        fault=combined.copy(); fault.loc[fault.index[-1],'original_allocation']=.123
        d=publish.divergence(combined,fault,'original')
        assert not d['terminal_equal'] and d['terminal_equal_tail_sessions']==0
    result={'status':'PASS','synthetic_sessions':260,'controller_tracks':6,
            'original_reference_clock_exact':True,'compact_accounting_restarts':checkpoints,
            'future_suffix_prefix_invariant':True,'same_session_allocation_mutant_rejected':True,
            'incomplete_reporting_and_lossless_tape_checks':True,'full_pit_starts':0}
    (v.HERE/'REPLAY_CONTRACT_CHECKS.json').write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
    print(json.dumps(result))


if __name__=='__main__': main()
