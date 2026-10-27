"""Pure timing observer and authority guards; canonical replay stays hosted."""
import io
import json
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).parents[1];sys.path.insert(0,str(ROOT))
from timing_observer import TimingObserver
from timing_pilot_worker import canonical_arguments
from timing_pilot_job import validate_request
from baseline_prefix import worker_stage,worker_arm


class TimingPilotGuards(unittest.TestCase):
    def test_observer_preserves_return_and_mutation_behavior(self):
        def observed(value):
            value['counter']+=1
            return value['counter']*2
        a,b=dict(counter=3),dict(counter=3)
        expected=observed(a);stream=io.StringIO()
        observer=TimingObserver(stream,{(observed.__code__.co_filename,observed.__name__):'synthetic'})
        prior=sys.getprofile();sys.setprofile(observer)
        try:actual=observed(b)
        finally:sys.setprofile(prior)
        self.assertEqual((actual,b),(expected,a));self.assertEqual(observer.active,{})
        records=list(map(json.loads,stream.getvalue().splitlines()))
        self.assertEqual(len(records),1);self.assertEqual(records[0]['ordinal'],0)
        self.assertEqual(records[0]['label'],'synthetic')
        self.assertGreaterEqual(records[0]['wall_seconds'],0);self.assertGreaterEqual(records[0]['cpu_seconds'],0)
        self.assertEqual(set(records[0]),{'label','ordinal','wall_seconds','cpu_seconds','returned_value'})

    def test_observer_preserves_exceptions_and_cleans_stack(self):
        def observed():raise RuntimeError('unchanged synthetic error')
        stream=io.StringIO();observer=TimingObserver(stream,{(observed.__code__.co_filename,observed.__name__):'synthetic'})
        prior=sys.getprofile();sys.setprofile(observer)
        try:
            with self.assertRaisesRegex(RuntimeError,'unchanged synthetic error'):observed()
        finally:sys.setprofile(prior)
        self.assertEqual(observer.active,{})
        self.assertFalse(json.loads(stream.getvalue())['returned_value'])

    def test_request_and_budget_cannot_expand_into_performance_run(self):
        r=json.loads((ROOT/'timing-pilot-request.json').read_bytes());p=validate_request(r)
        self.assertEqual((p['maximum_formation_transitions'],p['maximum_measured_closes'],p['worker_deadline_seconds'],p['job_timeout_minutes']),(5,0,300,15))
        for change in (dict(stage='short-core-window'),dict(pilot_protocol_sha256='0'*64),dict(worker_source_sha256='0'*64)):
            with self.assertRaises(ValueError):validate_request({**r,**change})
        args=canonical_arguments();self.assertEqual(args[args.index('--max-transitions')+1],'5')
        self.assertIn('--resume',args);self.assertEqual(args[args.index('--checkpoint')+1],'/out/run-001/checkpoint.json.gz')
        for name in ('capital-risk-timing-pilot-123-1','capital-risk-timing-pilot-123-1-review'):
            self.assertEqual((worker_stage(name),worker_arm(name)),('timing-pilot','B'))
        with self.assertRaises(ValueError):worker_stage('capital-risk-timing-pilot-123-1-restart')


if __name__=='__main__':unittest.main()
