"""Focused falsifiers: ramp deletion, EX3 compression, snapshot and peer edges."""
import copy
import json
import random

import numpy as np

import ablation_reference as ref
import variants as v


def rejects(fn):
    try:
        fn()
    except ValueError:
        return
    raise AssertionError('invalid snapshot accepted')


def check():
    sources = v.build_sources()
    env = {k:v.pure(s) for k,s in sources.items()}
    legacy_env = v.pure(sources['original'])
    exec(ref._native_variant_sources(sources['original'])['native_recovery_ramp'], legacy_env)
    legacy = legacy_env['NativeAblateRecoveryRamp']()
    states = {k:(e['Native'](),e['CandidateA']()) for k,e in env.items() if k.endswith('no_ramp')}
    rng = random.Random(350307)
    seen = set(); restarts = 0
    for i in range(30000):
        phase = i % 120
        healthy = phase >= 50
        ob = (rng.choice([None,-.20,-.155,-.1,-.06,-.059,-.03]),
              -.08 if phase<40 else .04, -.11 if phase<40 else .05,
              .04 if healthy else -.08, -.1 if phase<40 else .02,
              .3 if healthy else .95, .5 if healthy else .05, .35, -.05, .08,
              0 if healthy else 4, 110. if healthy else 85.)
        target_ref = legacy.step(ob)
        args = (rng.choice([0.,1.,None]), rng.choice([None,-.20,-.1,-.099]),
                rng.choice([None,float('nan'),-.10,-.085,0.,.02,.05]),
                rng.choice([None,-.04,-.039,.02]),
                rng.choice([None,-.02,0.,.04,.11,.12]), rng.choice([None,-.03,0.,.02]))
        results = {}
        for name,(n,c) in states.items():
            nt = n.step(ob)
            assert nt == target_ref, (i,name,nt,target_ref)
            result = c.step(nt[0], *args)
            results[name] = result
            seen.update(result[1].split('|'))
        for parent in ('original','simplified'):
            key = parent+'_no_ramp'; compact = 'compact_'+key
            assert results[key] == results[compact], (i,key,results)
            a,b = states[key][1],states[compact][1]
            assert (a.episodes,a.concordance_releases) == (b.episodes,b.concordance_releases)
            if a.episode: assert a.prev_desired == 0.
        if i%97 == 0:
            for name,(n,c) in list(states.items()):
                if name.startswith('compact'):
                    states[name] = (type(n).from_snapshot(json.loads(json.dumps(n.snapshot(),allow_nan=False))),
                                    type(c).from_snapshot(json.loads(json.dumps(c.snapshot(),allow_nan=False))))
                    restarts += 1
    for parent in ('original','simplified'):
        for recovery_r40 in (-.05, -.03):
            a=env[parent+'_no_ramp']['CandidateA']()
            b=env['compact_'+parent+'_no_ramp']['CandidateA']()
            trace=[(0.,1.,-.2,-.1,-.08,.04,-.04)]*4
            trace += [(1.,1.,-.05,.04,recovery_r40,.05,.02)]*12
            for args in trace:
                x,y=a.step(*args),b.step(*args)
                assert x==y
                seen.update(x[1].split('|'))
    assert {'FULL_RISK_HELD','LD_ENTER_DIVERGENCE','DIVERGENCE_CLEAR',
            'FULL_RISK_CERTIFIED_CROSS_SURFACE','FULL_RISK_CERTIFIED_PERSISTENCE'} <= seen, seen
    invalid = 0
    for name in ('compact_original_no_ramp','compact_simplified_no_ramp'):
        for cls in (env[name]['Native'],env[name]['CandidateA']):
            good=cls().snapshot()
            bad=copy.deepcopy(good); bad['schema']='legacy'; rejects(lambda:cls.from_snapshot(bad)); invalid+=1
            for field in good['state']:
                bad=copy.deepcopy(good); del bad['state'][field]
                rejects(lambda:cls.from_snapshot(bad)); invalid+=1
            bad=copy.deepcopy(good); bad['state']['unknown']=0
            rejects(lambda:cls.from_snapshot(bad)); invalid+=1
            for field,cap in cls._caps.items():
                for value in (-1,cap+1,True,1.5):
                    bad=copy.deepcopy(good); bad['state'][field]=value
                    rejects(lambda:cls.from_snapshot(bad)); invalid+=1
        rejects(lambda:env[name]['CandidateA']().step(.55,1.,0.,0.,0.,0.,0.))
    # Rebound can clear a latch while the entry signal remains true on the same close.
    c=env['compact_original_no_ramp']['CandidateA'](); c.latched=True
    assert c.step(1.,1.,-.12,-.10,-.05,.12,-.02)[0] == 1.
    # Peer vote and zero-red tests use independent functions with deterministic histories.
    peers=[env[k] for k in ('original','simplified','compact_simplified_no_ramp')]
    peer_cases=0
    for count in range(1,21):
        for iteration in range(100):
            histories={tid:{day:float(np.sin(day*.3+tid*.07)) for day in range(90)} for tid in range(count)}
            held=[(tid,0,rng.choice([-.11,-.10,-.099,.03]),rng.choice([-.031,-.03,0.]),0,0,
                   rng.choice([False,True]),False if iteration%5==0 else rng.choice([False,True]))
                  for tid in range(count)]
            actual=[]
            for e in peers:
                e['_prior_residuals']=lambda tid,*args:histories[tid]
                actual.append(e['dynamic_peer_breadth'](held,100,None,None,None))
            assert actual[0] == actual[1] == actual[2], (held,actual)
            peer_cases+=1
    manifest=v.write_sources()
    return {'status':'PASS','synthetic_observations':30000,'paired_controller_steps':120000,
            'snapshot_restarts':restarts,'invalid_snapshot_rejections':invalid,
            'independent_peer_cases':peer_cases,'reasons_seen':sorted(seen),
            'source_sha256':{k:x['sha256'] for k,x in manifest.items()},
            'scope':'Synthetic checks; fresh PIT and historical artifact comparisons pending.'}


if __name__ == '__main__':
    result=check()
    (v.HERE/'PREFLIGHT.json').write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
    print(json.dumps(result,sort_keys=True))
