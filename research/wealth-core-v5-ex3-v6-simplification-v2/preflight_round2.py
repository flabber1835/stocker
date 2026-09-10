"""Boundary, differential, restart and budget falsifiers; no market replay."""
import ast
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
import numpy as np
from round2_arms import VARIANTS, EXACT_ARMS, build, reference
from treatments import assert_scope
import preflight as prior_preflight
from run_round2 import driver, verify_artifact


def load(arm):
    with patch.object(prior_preflight,'build',lambda _:build(arm)):
        return prior_preflight.load(arm)


def observation(i,rng):
    healthy=(i//25)%4==0
    return (-.03 if healthy else -.20,-.07,-.11,.04 if healthy else -.06,
            rng.choice([-.09,.02,None]),.3 if healthy else .9,.5 if healthy else .1,
            .35,-.03,.08,0 if healthy else 4,110. if healthy else 90.)


def restart(obj,cls):
    state=json.loads(json.dumps(obj.__dict__))
    restored=cls();restored.__dict__.update(state)
    return restored


class Round2(unittest.TestCase):
    def test_all_sources_scope_and_state_removal(self):
        self.assertEqual(build('baseline'),reference())
        for v in VARIANTS:compile(build(v),v,'exec')
        with self.assertRaises(RuntimeError):
            assert_scope(reference(),reference().replace('cash:float=100000.0','cash:float=110000.0'),{'Native','CandidateA','dynamic_peer_breadth'})
        for v in ('cleanup_state','clean_cached','minimal_recovery'):
            n=load(v)['Native']();self.assertNotIn('ramp_idx',n.__dict__)
        self.assertNotIn('r40hist',load('fixed_ramp10')['Native']().__dict__)
        self.assertNotIn('recent_positive_streak',load('persistence_only')['CandidateA']().__dict__)
        for v in ('cleanup_state','clean_cached'):
            node=next(n for n in ast.parse(build(v)).body if getattr(n,'name',None)=='CandidateA')
            self.assertNotIn('FULL_RISK_CERTIFIED_SPY_V_REBOUND',ast.dump(node))

    def test_exact_controller_paths(self):
        rng=np.random.default_rng(350200)
        ref=load('baseline');rn=ref['Native']();rc=ref['CandidateA']()
        envs={v:load(v) for v in EXACT_ARMS}
        pairs={v:[e['Native'](),e['CandidateA']()] for v,e in envs.items()}
        seen=set()
        for i in range(20000):
            ob=observation(i,rng)
            if i%200==0:
                for n in [rn]+[pair[0] for pair in pairs.values()]:
                    n.fast=True;n.fast_age=9;n.fast_h=2;n.r40hist=[0.]*6
            x=rn.step(ob);seen.add(x[0])
            args=(x[0],float(rng.choice([0.,.55,1.])),ob[0],float(rng.choice([-.09,.04])),
                  float(rng.choice([-.05,-.03])),float(rng.choice([-.02,.05,.12])),ob[3])
            y=rc.step(*args)
            for v,(n,c) in pairs.items():
                self.assertEqual(n.step(ob),x,v);self.assertEqual(c.step(*args),y,v)
            if i%101==0:
                for v,(n,c) in pairs.items():pairs[v]=[restart(n,envs[v]['Native']),restart(c,envs[v]['CandidateA'])]
        self.assertEqual(seen,{0.,.55,1.})

    def test_all_arm_restart_equivalence(self):
        for v in VARIANTS:
            env=load(v);a=env['Native']();b=env['Native']();ca=env['CandidateA']();cb=env['CandidateA']()
            rng=np.random.default_rng(350201)
            for i in range(1000):
                ob=observation(i,rng);x=a.step(ob);self.assertEqual(b.step(ob),x,v)
                args=(x[0],1.,ob[0],.04,-.03,.06,ob[3])
                self.assertEqual(ca.step(*args),cb.step(*args),v)
                if i%17==0:b=restart(b,env['Native']);cb=restart(cb,env['CandidateA'])

    def test_pair_symmetry_and_session_cache(self):
        rng=np.random.default_rng(350202)
        base=load('baseline');cached=load('symmetric_peers');clean=load('clean_cached')
        rows=[{i:float(x) for i,x in enumerate(rng.normal(size=130))} for _ in range(20)]
        rows[1]=rows[0];rows[2]={};rows[3]={i:1. for i in range(130)}
        for left in rows:
            for right in rows:self.assertEqual(base['_peer_corr'](left,right),base['_peer_corr'](right,left))
        for env in (base,cached,clean):env['_prior_residuals']=lambda tid,*_:rows[tid]
        for _ in range(300):
            held=[(int(t),None,float(rng.choice([-.1,-.02,np.nan])),float(rng.choice([-.03,-.01,np.nan])),None,None,
                   bool(rng.integers(2)),bool(rng.integers(2))) for t in rng.permutation(20)[:int(rng.integers(21))]]
            args=(held,0,None,None,None);expected=base['dynamic_peer_breadth'](*args)
            self.assertEqual(cached['dynamic_peer_breadth'](*args),expected)
            self.assertEqual(clean['dynamic_peer_breadth'](*args),expected)
        # A threshold-tie cohort requires all reverse lookups to share the first result.
        held=[(i,None,-.02,-.01,None,None,False,i<10) for i in range(20)]
        for env in (base,cached,clean):
            env['_prior_residuals']=lambda tid,*_:{0:tid+1.}
            env['_peer_corr']=lambda *args:.145
            env['PEER_STATS']['pair_correlations']=0
        args=(held,0,None,None,None);expected=base['dynamic_peer_breadth'](*args)
        self.assertEqual(cached['dynamic_peer_breadth'](*args),expected)
        self.assertEqual(base['PEER_STATS']['pair_correlations'],380)
        self.assertEqual(cached['PEER_STATS']['pair_correlations'],190)
        # Next session has no correlations; cached results must be discarded.
        for env in (base,cached):env['_peer_corr']=lambda *args:None
        self.assertEqual(cached['dynamic_peer_breadth'](*args),base['dynamic_peer_breadth'](*args))
        self.assertEqual(cached['PEER_STATS']['pair_correlations'],380)

    def test_economic_removal_falsifiers(self):
        healthy=(-.03,.02,.03,.04,.05,.3,.5,0.,.06,0.,0,110.)
        ref=load('baseline')['Native']();fixed=load('fixed_ramp10')['Native']()
        for n in (ref,fixed):n.fast=True;n.fast_age=9;n.fast_h=2
        ref.r40hist=[-.05,-.04,-.03,-.02,-.01,0.]
        self.assertEqual(ref.step(healthy)[0],1.)
        self.assertEqual(fixed.step(healthy)[0],.55)
        # Recovery entry contributes one healthy close; the prior-close check releases later.
        for _ in range(9):self.assertEqual(fixed.step(healthy)[0],.55)
        self.assertEqual(fixed.step(healthy)[0],1.)
        refc=load('baseline')['CandidateA']();persist=load('persistence_only')['CandidateA']()
        for c in (refc,persist):c.episode=True;c.prev_desired=.55
        refc.recent_positive_streak=7
        args=(1.,1.,-.02,.06,-.05,.07,.04)
        self.assertEqual(refc.step(*args)[0],1.);self.assertEqual(persist.step(*args)[0],.55)
        peer=load('baseline');nopeer=load('no_peers')
        peer['_prior_residuals']=lambda tid,*_:{0:tid+1.};peer['_peer_corr']=lambda *args:.5
        held=[(0,None,-.02,-.01,None,None,False,False),(1,None,-.12,-.04,None,None,False,True),(2,None,-.12,-.04,None,None,False,True)]
        self.assertEqual(peer['dynamic_peer_breadth'](held,0,None,None,None)[1],1.)
        self.assertEqual(nopeer['dynamic_peer_breadth'](held,0,None,None,None)[1],2/3)

    def test_summary_source_guard_and_dual_screen(self):
        import hashlib
        from aggregate_round2 import verify_completed
        from aggregate import screen_window
        from round2_arms import BASELINE_RESULT
        baseline=BASELINE_RESULT['windows']['20']
        original={'cagr':.21557225805610547,'max_drawdown':-.2737554573856501,'ending_multiple':49.61927543842201}
        self.assertTrue(screen_window(baseline,baseline)['pass'])
        self.assertFalse(screen_window(baseline,original)['pass'])
        with TemporaryDirectory() as d,patch.dict('os.environ',{'GITHUB_SHA':'a'*40,'GITHUB_RUN_ID':'test'}):
            root=Path(d);p=root/'simplification-baseline';(p/'engine').mkdir(parents=True)
            result={'variant':'baseline','status':'PASS_FRESH_CAUSAL_PIT_REPLAY','source':{'experiment_head':'a'*40,'run_id':'test'}}
            (p/'RESULT.json').write_text(json.dumps(result))
            (p/'generated.py').write_text(build('baseline').replace('N_SLOTS = 20','N_SLOTS = 19'))
            (p/'engine/daily.csv').write_text('date\n')
            (p/'SLOT_CLAIM.json').write_text(json.dumps({'ref':'refs/heads/research-budget/simplification-v2/slot-01','sha':'a'*40}))
            (p/'SHA256.json').write_text(json.dumps({str(f.relative_to(p)):hashlib.sha256(f.read_bytes()).hexdigest() for f in p.rglob('*') if f.is_file()}))
            with self.assertRaisesRegex(RuntimeError,'generated arm source mismatch'):verify_completed(root)

    def test_publication_preserves_branch_and_parent(self):
        from aggregate_round2 import publish_files, BRANCH
        calls=[]
        def fake_api(path,data=None,method=None):
            calls.append((path,data,method))
            if path.startswith('/git/ref/'):return {'object':{'sha':'parent'}}
            if path=='/git/commits/parent':return {'tree':{'sha':'base-tree'}}
            if path=='/git/trees':return {'sha':'new-tree'}
            if path=='/git/commits':return {'sha':'new-commit'}
            if path.startswith('/git/refs/'):return {'object':{'sha':'new-commit'}}
            raise AssertionError(path)
        with TemporaryDirectory() as d,patch.dict('os.environ',{'GITHUB_RUN_ID':'test','GITHUB_RUN_ATTEMPT':'1'}),patch('aggregate_round2.api',side_effect=fake_api):
            p=Path(d);(p/'RESULTS.md').write_text('verified result')
            result=publish_files(p)
        tree=calls[2][1];commit=calls[3][1];ref=calls[4]
        self.assertEqual(tree['base_tree'],'base-tree')
        self.assertEqual(tree['tree'][0]['content'],'verified result')
        self.assertEqual(commit['parents'],['parent'])
        self.assertEqual(ref[0],'/git/refs/heads/'+BRANCH)
        self.assertIs(ref[1]['force'],False)
        self.assertEqual(result['commit'],'new-commit')

    def test_budget_and_artifact_guards(self):
        env={'__name__':'preflight_driver'};exec(compile(driver(),'<driver>','exec'),env)
        with patch.dict('os.environ',{'GITHUB_REPOSITORY':'flabber1835/stocker','GITHUB_SHA':'a'*40,'GITHUB_RUN_ID':'test','GH_TOKEN':'dummy'}),patch('urllib.request.urlopen') as request:
            request.side_effect=HTTPError('https://api.github.com',422,'exists',{},None)
            with self.assertRaises(HTTPError):env['claim_slot']('minimal_recovery')
            payload=json.loads(request.call_args.args[0].data)
            self.assertEqual(payload['ref'],'refs/heads/research-budget/simplification-v2/slot-10')
            self.assertEqual(request.call_count,1)
            with self.assertRaises(ValueError):env['claim_slot']('eleventh')
            self.assertEqual(request.call_count,1)
        with TemporaryDirectory() as d:
            p=Path(d);(p/'data').write_text('bad');(p/'SHA256.json').write_text(json.dumps({'data':'0'*64}))
            with self.assertRaisesRegex(RuntimeError,'checksum mismatch'):verify_artifact(p,'x','x','x','x')
            (p/'SHA256.json').write_text('{}')
            with self.assertRaisesRegex(RuntimeError,'missing artifact checksum'):verify_artifact(p,'x','x','x','x')


if __name__=='__main__':unittest.main(verbosity=2)
