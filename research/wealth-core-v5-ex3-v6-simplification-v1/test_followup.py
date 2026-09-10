import ast
import unittest
from unittest.mock import patch
import numpy as np
import candidate_followup as candidate
import preflight
from treatments import assert_scope, oracle


def load_candidate():
    with patch.object(preflight,'build',lambda _:candidate.build()):
        return preflight.load('candidate')


class Followup(unittest.TestCase):
    def test_baseline_artifact_tamper_and_missing_checksums(self):
        from tempfile import TemporaryDirectory
        from pathlib import Path
        import json
        with TemporaryDirectory() as d:
            root=Path(d)
            (root/'data').write_text('corrupted')
            (root/'SHA256.json').write_text(json.dumps({'data':'0'*64}))
            with self.assertRaisesRegex(RuntimeError,'checksum mismatch'):
                candidate.verify_baseline(root)
            (root/'SHA256.json').write_text('{}')
            with self.assertRaisesRegex(RuntimeError,'missing baseline checksum'):
                candidate.verify_baseline(root)

    def test_composition_and_budget(self):
        s=candidate.build()
        assert_scope(oracle(),s,{'Native','CandidateA','dynamic_peer_breadth'})
        self.assertIn('if self.ramp_idx>=1:',s)
        self.assertIn('self.ramp_h=min(self.ramp_h,10)',s)
        self.assertEqual(candidate.VARIANTS,('candidate',))
        d=candidate.driver()
        self.assertIn('research-budget/simplification-candidate-v1/slot-',d)
        self.assertIn("'experiment_budget':1",d)
        self.assertIn('baseline=verify_baseline(args.baseline)',d)
        with self.assertRaises(ValueError): candidate.build('baseline')

    def test_combined_state_differential(self):
        rng=np.random.default_rng(35011)
        env=load_candidate(); n=env['Native'](); c=env['CandidateA']()
        refn=preflight.load('ramp10')['Native'](); refc=preflight.load('no_spy_rebound')['CandidateA']()
        seen=set()
        for i in range(20000):
            healthy=(i//30)%4==0
            if i%200==0:
                for obj in (n,refn):
                    obj.fast=True;obj.fast_age=9;obj.r40hist=[0.]*6
            ob=(-.03 if healthy else -.20,-.07,-.11,.04 if healthy else -.06,
                rng.choice([-.09,.02,None]),.3 if healthy else .9,.5 if healthy else .1,
                .35,-.03,.08,0 if healthy else 4,110. if healthy else 90.)
            x=n.step(ob);self.assertEqual(x,refn.step(ob));seen.add(x[0])
            args=(x[0],1.,ob[0],float(rng.choice([-.09,.04])),float(rng.choice([-.05,-.03])),
                  float(rng.choice([-.02,.05,.12])),ob[3])
            self.assertEqual(c.step(*args),refc.step(*args))
            self.assertLessEqual(c.full_streak,8)
        self.assertEqual(seen,{0.,.55,1.})
        # The candidate includes the exact already-tested selective peer function.
        def peer(s):
            return ast.dump(next(n for n in ast.parse(s).body if getattr(n,'name',None)=='dynamic_peer_breadth'))
        self.assertEqual(peer(candidate.build()),peer(preflight.build('selective_peers')))


if __name__=='__main__':unittest.main(verbosity=2)
