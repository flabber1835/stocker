"""Cheap controller falsifiers; never loads a market dataset or calls run()."""
import ast
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
import numpy as np
from treatments import VARIANTS, CAPS, build, oracle, assert_scope


def load(variant):
    names = {'finite', 'Native', 'CandidateA', 'dynamic_peer_breadth', '_peer_corr', '_prior_residuals'}
    tree = ast.parse(build(variant))
    nodes = [n for n in tree.body if getattr(n, 'name', None) in names]
    env = dict(np=np, ORD_DD=-.155,
        FAST={'dd':-.10,'dam':.88,'green':.20,'r5':-.05,'r10':-.08,'ddam5':.30,'volacc':.04,'spy20':-.01,'r10confirm':-.10},
        SLOW={'dur':30,'ret':-.02,'r40':-.03,'dam':.75,'green':.25},
        LDRC_DD=-.1,LDRC_R20=-.085,LDRC_CEIL=.55,LDRC_REC=8,LDRC_V=.11,
        PEER_LOOKBACK=252,PEER_MIN_OBS=120,PEER_COUNT=3,PEER_CORR_FLOOR=.145,
        PEER_STATS={k:0 for k in ('breadth_sessions','holding_observations','insufficient_residual_histories','pair_correlations','accepted_peer_edges','neighborhood_size_sum')})
    exec(compile(ast.Module(body=nodes,type_ignores=[]),'<pure-controller>', 'exec'),env)
    return env


class Preflight(unittest.TestCase):
    def test_screen_boundaries_and_missing_evidence(self):
        from aggregate import screen_window, aggregate
        from tempfile import TemporaryDirectory
        from pathlib import Path
        base={'cagr':.20,'max_drawdown':-.25,'ending_multiple':40.}
        self.assertTrue(screen_window(base,base)['pass'])
        for key,value in [('cagr',.202501),('cagr',.197499),('max_drawdown',-.260001),
                          ('ending_multiple',42.001),('ending_multiple',37.999)]:
            candidate={**base,key:value}
            self.assertFalse(screen_window(candidate,base)['pass'],(key,value))
        with TemporaryDirectory() as d:
            result=aggregate(Path(d))
            self.assertEqual(result['status'],'INCOMPLETE')
            self.assertEqual(len(result['missing_or_failed']),10)
            self.assertEqual(result['screening'],{})

    def test_budget_claim_failure_has_no_retry(self):
        from run_experiment import claim_slot
        environment={'GITHUB_REPOSITORY':'flabber1835/stocker','GITHUB_SHA':'a'*40,
                     'GITHUB_RUN_ID':'test','GH_TOKEN':'dummy-test-token'}
        with patch.dict('os.environ',environment), patch('urllib.request.urlopen') as request:
            request.side_effect=HTTPError('https://api.github.com',422,'reference exists',{},None)
            with self.assertRaises(HTTPError): claim_slot('baseline')
            self.assertEqual(request.call_count,1)
            payload=__import__('json').loads(request.call_args.args[0].data)
            self.assertEqual(payload['ref'],'refs/heads/research-budget/simplification-v1/slot-01')
            with self.assertRaises(ValueError): claim_slot('eleventh_arm')
            self.assertEqual(request.call_count,1)

    def test_all_sources_and_scope_falsifier(self):
        self.assertEqual(build('baseline'), oracle())
        for variant in VARIANTS:
            compile(build(variant), variant, 'exec')
        with self.assertRaises(RuntimeError):
            assert_scope(oracle(),oracle().replace('N_SLOTS = 20','N_SLOTS = 19'),{'Native','CandidateA','dynamic_peer_breadth'})

    def test_bounded_state_random_and_seeded(self):
        rng=np.random.default_rng(260910)
        a=load('baseline'); b=load('bounded_counters')
        na=a['Native'](); nb=b['Native'](); ca=a['CandidateA'](); cb=b['CandidateA']()
        seen=set()
        # Seed long-lived states as well as sequential regime paths, so saturation is exercised.
        for i in range(20000):
            if i%100==0:
                state=a['Native']().__dict__.copy()
                for key in ('ordinary','base_fast','fast','slow','ramp'):
                    state[key]=bool(rng.integers(2))
                for key in CAPS:
                    state[key]=int(rng.integers(0,80))
                state['ramp_idx']=int(rng.integers(2)) if state['ramp'] else None
                state['base_anchor']=100. if state['ordinary'] or state['base_fast'] else None
                state['r40hist']=[float(x) for x in rng.uniform(-.15,.1,6)]
                na.__dict__.update(state); nb.__dict__.update(state)
            regime=(i//25)%4
            healthy=regime==0
            ob=(-.20 if not healthy else -.03, -.07, -.11,
                .04 if healthy else -.06, rng.choice([-.09,.02,None]),
                .30 if healthy else .90, .50 if healthy else .10,
                .35, -.03, .08, 0 if healthy else 4, 90. if not healthy else 110.)
            x=na.step(ob); y=nb.step(ob); self.assertEqual(x,y)
            seen.add(x[0])
            values=[x[0],float(rng.choice([0.,.55,.65,1.])),ob[0],float(rng.choice([-.09,.04])),float(rng.choice([-.05,-.03])),float(rng.choice([-.02,.05,.12])),ob[3]]
            self.assertEqual(ca.step(*values), cb.step(*values))
            for k,v in CAPS.items(): self.assertLessEqual(getattr(nb,k),v)
        self.assertEqual(seen,{0.,.55,.65,1.})

    def test_selective_peers_differential_and_missing_ties(self):
        a=load('baseline'); b=load('selective_peers'); rng=np.random.default_rng(349)
        # Include identical residual series (tie-breaking), absent histories, NaNs and inconsistent colors.
        arrays=[{i:float(x) for i,x in enumerate(rng.normal(size=130))} for _ in range(20)]
        arrays[1]=arrays[0]; arrays[2]={}
        for env in (a,b): env['_prior_residuals']=lambda tid,*_: arrays[tid]
        for _ in range(300):
            held=[]
            for tid in rng.permutation(20)[:int(rng.integers(0,21))]:
                dd=float(rng.choice([-.11,-.10,-.075,-.02,np.nan]))
                r21=float(rng.choice([-.04,-.03,0.,.03,np.nan]))
                held.append((int(tid),None,dd,r21,None,None,bool(rng.integers(2)),bool(rng.integers(2))))
            args=(held,0,None,None,None)
            self.assertEqual(a['dynamic_peer_breadth'](*args),b['dynamic_peer_breadth'](*args))
        self.assertLess(b['PEER_STATS']['pair_correlations'],a['PEER_STATS']['pair_correlations'])
        # Settled red stocks must still be peers of an unresolved holding.
        for env in (a,b):
            env['_prior_residuals']=lambda *args: arrays[0]
        held=[(0,None,-.02,-.01,None,None,False,False),
              (1,None,-.12,-.04,None,None,False,True),
              (3,None,-.12,-.04,None,None,False,True)]
        self.assertEqual(b['dynamic_peer_breadth'](held,0,None,None,None),(0.,1.))
        self.assertEqual(load('no_peers')['dynamic_peer_breadth'](held,0,None,None,None),(0.,2/3))

    def test_ramp_timing_and_reset(self):
        healthy=(-.02,.02,.03,.04,-.03,.3,.5,0.,.01,0.,0,100.)
        for arm,days in [('baseline',10),('ramp10',10),('ramp20',20),('combined',20)]:
            n=load(arm)['Native'](); n.ramp=True;n.ramp_idx=0;n.ramp_h=0
            for _ in range(days): self.assertEqual(n.step(healthy)[0],.55)
            self.assertEqual(n.step(healthy)[0],.65 if arm=='baseline' else 1.)
        n=load('ramp20')['Native']();n.ramp=True;n.ramp_idx=0;n.ramp_h=19
        bad=list(healthy);bad[3]=-.01
        self.assertEqual(n.step(bad)[0],.55);self.assertEqual(n.ramp_h,0)

    def test_output_mapping_preserves_memory(self):
        a=load('baseline')['CandidateA']();b=load('map65_to55')['CandidateA']()
        self.assertEqual(a.step(.65,.55,-.02,.02,.02,.02,.02)[0],.65)
        self.assertEqual(b.step(.65,.55,-.02,.02,.02,.02,.02)[0],.55)
        self.assertEqual(a.__dict__,b.__dict__)

    def test_route_removal_falsifiers(self):
        for treatment,route in [('no_cross_surface','cross'),('no_spy_rebound','spy')]:
            a=load('baseline')['CandidateA']();b=load(treatment)['CandidateA']()
            for obj in (a,b):
                obj.episode=True;obj.prev_desired=.55;obj.recent_positive_streak=7
            args=(1.,1.,-.02,.06,-.05,.07 if route=='cross' else .12,.04)
            # For rebound removal also suppress the cross route.
            if route=='spy': args=(*args[:-1],.10)
            self.assertEqual(a.step(*args)[0],1.)
            self.assertEqual(b.step(*args)[0],.55)


if __name__=='__main__': unittest.main(verbosity=2)
