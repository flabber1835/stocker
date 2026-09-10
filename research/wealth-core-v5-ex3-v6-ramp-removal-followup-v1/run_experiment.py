"""Exactly one claimed Core start per job, followed by reusable controller replay."""
import argparse
from collections import Counter
import hashlib
import inspect
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd

import ablation_reference as ref
import variants as v

OLD_IDS = {'301606049357818446','1040633074096912075','277347208162984956',
           '727329233939509358','425931792436652190','311453645065866101'}
CASES = ('baseline','loo_0','loo_1','loo_2','drop_29','drop_47','drop_83')


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False)+'\n')


def read_csv(path):
    return pd.read_csv(path, parse_dates=['date'], float_precision='round_trip')


def require_pair(a,b,tolerance=0.,reasons=True):
    assert len(a)==len(b) and np.array_equal(a.date.to_numpy(),b.date.to_numpy()), 'date mismatch'
    checks={}
    for col in ('allocation','nav','native_close_target','effective_native','close_desired'):
        if col not in a or col not in b: continue
        x,y=a[col].to_numpy(float),b[col].to_numpy(float)
        assert np.isfinite(x).all() and np.isfinite(y).all(), col
        delta=float(np.max(np.abs(x-y)))
        checks[col]=delta
        assert delta <= (tolerance if col=='nav' else 0.), (col,delta,tolerance)
    if reasons and 'close_reason' in a and 'close_reason' in b:
        checks['reason_mismatches']=int((a.close_reason!=b.close_reason).sum())
        assert checks['reason_mismatches']==0
    for col in ('fast_signal','slow_signal'):
        if col in a and col in b:
            assert np.array_equal(a[col].to_numpy(),b[col].to_numpy()), col
    return checks


def install_peer_checks(module,sources):
    original=module.dynamic_peer_breadth
    prior=module._prior_residuals
    envs=[v.pure(sources[k]) for k in ('simplified','compact_simplified_no_ramp')]
    audit={'calls':0,'residual_lookups':0,'residual_cache_hits':0,'mismatches':0}
    def wrapped(*args):
        cache={}
        def residual(tid,*rest):
            if tid not in cache:
                cache[tid]=prior(tid,*rest); audit['residual_lookups']+=1
            else: audit['residual_cache_hits']+=1
            return cache[tid]
        module._prior_residuals=residual
        try:
            expected=original(*args)
            for env in envs:
                env['_prior_residuals']=residual
                actual=env['dynamic_peer_breadth'](*args)
                if actual!=expected:
                    audit['mismatches']+=1
                    raise RuntimeError(f'peer breadth mismatch at session {args[1]}: {expected} vs {actual}')
        finally:
            module._prior_residuals=prior
        audit['calls']+=1
        return expected
    module.dynamic_peer_breadth=wrapped
    audit['original_stats']=module.PEER_STATS
    audit['cached_stats']=envs[0]['PEER_STATS']
    audit['zero_red_integer_stats']=envs[1]['PEER_STATS']
    return audit


def claim(case,out):
    from publish import api
    slot=CASES.index(case)+1
    receipt={'slot':slot,'case':case,'sha':os.environ['GITHUB_SHA'],
             'run_id':os.environ['GITHUB_RUN_ID'],'run_attempt':os.environ['GITHUB_RUN_ATTEMPT'],
             'ref':f'refs/heads/research-budget/simplification-ramp-v1/slot-{slot:02d}'}
    # Creation is atomic: an existing ref fails, including manual job reruns.
    response=api('/git/refs',{'ref':receipt['ref'],'sha':receipt['sha']})
    assert response['ref']==receipt['ref'] and response['object']['sha']==receipt['sha']
    write_json(out/'SLOT.json',receipt)
    print('[SLOT_CLAIMED] '+json.dumps(receipt),flush=True)
    return receipt


def replay(module,obs,ncls,ccls,restart=False):
    n,c=ncls(),ccls()
    pn=en=pa=ea=nav=1.
    prev_eq=prev_date=None
    rows=[]; checkpoint_count=0; last_target=None
    _,bil=module.load_funds()
    for index,r in enumerate(obs.itertuples(index=False)):
        date=pd.Timestamp(r.date)
        ob=tuple(float(getattr(r,k)) for k in ('dd','r5','r10','r20','r40','dam','green','ddam5','spy20','volacc'))+(int(r.stops20),float(r.nav))
        nt,fast,slow=n.step(ob)
        desired,reason=c.step(nt,en,float(r.dd),float(r.recent_r20),float(r.recent_r40),float(r.spy20),float(r.r20))
        if ref._as_bool(r.measured):
            en=pn
            if prev_eq is None:
                ea=pa
            else:
                nav,_=module.apply_overlay(nav,ea,pa,prev_eq,float(r.open_eq),float(r.close_eq),bil,date,prev_date)
                ea=pa
            rows.append(dict(date=date,allocation=ea,nav=nav,native_close_target=nt,
                             effective_native=en,close_desired=desired,close_reason=reason,
                             fast_signal=fast,slow_signal=slow))
            prev_date,prev_eq=date,float(r.close_eq)
        pn,pa=float(nt),float(desired)
        if restart and (index%97==0 or desired!=last_target):
            payload=dict(native=n.snapshot(),ex3=c.snapshot(),pn=pn,en=en,pa=pa,ea=ea,nav=nav,
                         prev_eq=prev_eq,prev_date=None if prev_date is None else prev_date.isoformat())
            payload=json.loads(json.dumps(payload,allow_nan=False))
            n=ncls.from_snapshot(payload['native']); c=ccls.from_snapshot(payload['ex3'])
            pn,en,pa,ea,nav,prev_eq=(payload[k] for k in ('pn','en','pa','ea','nav','prev_eq'))
            prev_date=None if payload['prev_date'] is None else pd.Timestamp(payload['prev_date'])
            checkpoint_count+=1
        last_target=desired
    return pd.DataFrame(rows),{'restarts':checkpoint_count,'episodes':c.episodes,
                               'concordance_releases':c.concordance_releases}


def fault_selection(daily):
    counts=Counter()
    for raw in daily.research_selected_positions:
        ids=json.loads(raw)
        counts.update(set(map(str,ids)))
    ranked=sorted(((sid,count) for sid,count in counts.items() if sid not in OLD_IDS),key=lambda x:(-x[1],x[0]))
    assert len(ranked)>=3
    return {'rule':'Top three measured holding-session counts excluding prior six; permanent-ID lexical ties',
            'selected':[{'security_id':sid,'holding_sessions':count} for sid,count in ranked[:3]],
            'prior_excluded':sorted(OLD_IDS),'dropout_seeds':[29,47,83]}


def historical_checks(args,frames,engine_result):
    old=read_csv(args.old_ablation/'ablation-daily.csv')
    meta=json.loads((args.old_ablation/'RESULT.json').read_text())
    assert meta['experiment_head']=='ddabaa9ac5c35a722c1f429fad4192a6d232b7b2'
    assert meta['baseline']['dataset_sha256']==engine_result['dataset_sha256']
    assert meta['baseline']['core_tape_sha256']==engine_result['core_tape_sha256']
    checks={}
    for new,old_name in [('original','current'),('original_no_ramp','native_recovery_ramp')]:
        prior=old.rename(columns={old_name+'_allocation':'allocation',old_name+'_nav':'nav',
                                  old_name+'_native_close_target':'native_close_target',
                                  old_name+'_close_reason':'close_reason'})
        checks[new]=require_pair(frames[new],prior,1e-10)
    candidates=list(args.old_simplified.rglob('generated.py'))
    # Prior runner stores the generated source under a descriptive filename on some versions.
    if not candidates:
        candidates=[p for p in args.old_simplified.rglob('*.py') if v.sha(p.read_text())==v.SIMPLIFIED_SHA]
    assert any(v.sha(p.read_text())==v.SIMPLIFIED_SHA for p in candidates), 'simplified artifact source hash'
    daily_paths=list(args.old_simplified.rglob('daily.csv'))
    assert daily_paths, 'simplified artifact daily missing'
    previous=read_csv(daily_paths[0]).rename(columns={'A_allocation':'allocation','A_nav':'nav','A_reason':'close_reason'})
    checks['simplified']=require_pair(frames['simplified'],previous,1e-10)
    return checks


def verify_prior_inputs(args):
    """Reject unavailable/corrupt inputs before consuming the baseline slot."""
    old=json.loads((args.old_ablation/'RESULT.json').read_text())
    assert old['experiment_head']=='ddabaa9ac5c35a722c1f429fad4192a6d232b7b2'
    assert (args.old_ablation/'ablation-daily.csv').is_file()
    root=args.old_simplified.resolve()
    checks=json.loads((root/'SHA256.json').read_text())
    for name in ('RESULT.json','engine/daily.csv','generated.py'):
        assert name in checks
        assert hashlib.sha256((root/name).read_bytes()).hexdigest()==checks[name], name
    prior=json.loads((root/'RESULT.json').read_text())
    assert prior['variant']=='clean_cached'
    assert str(prior['source']['run_id'])=='34480037109'
    assert prior['source']['experiment_head']=='5dfcdd4135d3f5a98ff923a3d0be62f147cacc2b'
    assert prior['source']['candidate_sha256']==v.SIMPLIFIED_SHA
    assert v.sha((root/'generated.py').read_text())==v.SIMPLIFIED_SHA


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--case',choices=CASES,required=True)
    ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--baseline',type=Path)
    ap.add_argument('--old-ablation',type=Path)
    ap.add_argument('--old-simplified',type=Path)
    args=ap.parse_args(); out=args.output.resolve(); out.mkdir(parents=True,exist_ok=True)
    sources=v.build_sources()
    manifest=json.loads((v.HERE/'SOURCE_MANIFEST.json').read_text())
    assert all(manifest[k]['sha256']==v.sha(s) for k,s in sources.items())
    if args.case=='baseline':
        verify_prior_inputs(args)
    else:
        prior=json.loads((args.baseline/'RESULT.json').read_text())
        assert prior['status']=='PASS' and prior['case']=='baseline'
        assert prior['slot']['sha']==os.environ['GITHUB_SHA']
        assert prior['sources']==manifest
        hashes=json.loads((args.baseline/'SHA256.json').read_text())
        for filename in ('RESULT.json','FAULT_SELECTION.json'):
            assert hashlib.sha256((args.baseline/filename).read_bytes()).hexdigest()==hashes[filename]
    base=ref.load(Path(os.environ['RAMP_V6_RUNNER']))
    assert base.SELECTED==ref.EXPECTED_V6
    workspace=Path(os.environ['GITHUB_WORKSPACE'])
    exact=base.build_selected(workspace/'open-src/research/wealth-core-v1-buffer-sweep-evidence/arms/10bp/buffer-10bp-generated.py',
                              workspace/'median-src/research/median5-fullpit-recertification-v13/experiment_overlay.py')
    assert exact==sources['original']
    selected=ref.telemetry_source(exact)
    fault={'type':'none'}
    if args.case.startswith('loo_'):
        selection=json.loads((args.baseline/'FAULT_SELECTION.json').read_text())
        sid=selection['selected'][int(args.case[-1])]['security_id']
        assert sid not in OLD_IDS
        selected=base.patch_exclusion(selected,{sid}); fault={'type':'security_exclusion','security_id':sid}
    elif args.case.startswith('drop_'):
        seed=int(args.case.split('_')[1]); selected=base.patch_dropout(selected,.01,seed)
        fault={'type':'universe_dropout','fraction':.01,'seed':seed}
    base.timing_guard(selected)
    held={}; claims=[]
    def prepare(module):
        assert not claims, 'second Core start forbidden'
        held['module']=module; held['peers']=install_peer_checks(module,sources)
        claims.append(claim(args.case,out))
    execute_source=inspect.getsource(base.execute)
    execute_source=v.replace(execute_source,'    module.OUT = engine\n    module.run()',
                            '    module.OUT = engine\n    prepare(module)\n    module.run()')
    env=dict(base.__dict__,prepare=prepare)
    exec(compile(execute_source,'<one-start-driver>','exec'),env)
    write_json(out/'PROVENANCE.json',dict(case=args.case,fault=fault,experiment_head=os.environ['GITHUB_SHA'],
              sources=manifest,instrumented_source_sha256=v.sha(selected),
              execute_sha256=v.sha(execute_source),reference_sha256=v.REFERENCE_SHA))
    result=env['execute'](selected,out/'core',args.case,False)
    write_json(out/'CORE_RESULT.json',result)
    assert len(claims)==1
    if args.case=='baseline': base.assert_baseline(result)
    daily=read_csv(out/'core/engine/daily.csv'); obs=read_csv(out/'core/engine/ablation-observations.csv')
    assert len(daily)==5032 and int(obs.measured.map(ref._as_bool).sum())==5032
    assert obs.date.is_monotonic_increasing and not obs.date.duplicated().any()
    module=held['module']; frames={}; audits={}; tracks={}; checks={}
    combined=daily[['date','research_selected_positions','shadow_equity']].copy()
    for name,source in sources.items():
        pure=v.pure(source)
        frame,audit=replay(module,obs,pure['Native'],pure['CandidateA'])
        frames[name]=frame; audits[name]=audit
        for col in frame.columns:
            if col!='date': combined[name+'_'+col]=frame[col]
        tracks[name]={'metrics':base.imp.windows(frame,'nav'),'allocation':ref.allocation_counts(frame,'allocation'),'audit':audit}
        if name.startswith('compact_'):
            restarted,restart_audit=replay(module,obs,pure['Native'],pure['CandidateA'],restart=True)
            checks[name+'_restart']=require_pair(frame,restarted)
            assert audit['episodes']==restart_audit['episodes'] and audit['concordance_releases']==restart_audit['concordance_releases']
            checks[name+'_restart']['checkpoints']=restart_audit['restarts']
    checks['engine_reconstruction']=require_pair(frames['original'],daily.rename(columns={
        'A_allocation':'allocation','A_nav':'nav','A_reason':'close_reason'}),1e-10)
    reference_env=v.pure(exact)
    exec(ref._native_variant_sources(exact)['native_recovery_ramp'],reference_env)
    legacy,_=replay(module,obs,reference_env['NativeAblateRecoveryRamp'],reference_env['CandidateA'])
    checks['legacy_ramp_ablation']=require_pair(frames['original_no_ramp'],legacy)
    for parent in ('original','simplified'):
        key=parent+'_no_ramp'; checks['compact_'+key]=require_pair(frames[key],frames['compact_'+key])
    combined.to_csv(out/'daily-tracks.csv',index=False)
    obs.to_csv(out/'observations.csv',index=False)
    write_json(out/'PEER_CHECKS.json',held['peers'])
    if args.case=='baseline':
        checks['historical_artifacts']=historical_checks(args,frames,result)
        write_json(out/'FAULT_SELECTION.json',fault_selection(daily))
    report=dict(status='PASS',case=args.case,fault=fault,slot=claims[0],core=result,
                tracks=tracks,checks=checks,peer_checks=held['peers'],sources=manifest)
    write_json(out/'RESULT.json',report)
    write_json(out/'SHA256.json',{str(p.relative_to(out)):hashlib.sha256(p.read_bytes()).hexdigest()
                                for p in sorted(out.rglob('*')) if p.is_file() and p.name!='SHA256.json'})
    print('[HEADLINES] '+json.dumps({k:t['metrics']['20'] for k,t in tracks.items()},sort_keys=True),flush=True)


if __name__=='__main__':
    main()
