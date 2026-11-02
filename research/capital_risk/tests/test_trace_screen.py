"""Synthetic falsifiers only. The actual canonical trace integration is hosted."""
import copy
import importlib.util
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT=Path(__file__).parents[1]
sys.path.insert(0,str(ROOT))
import trace_screen as s
from screen_job import validate_request, screen_command
from baseline_prefix import launch_arguments, worker_stage, worker_arm
from runtime_identity import EXECUTION_IMAGE
from seal import sha256_file


def row(day='2008-02-22',*,phase='MEASURED',native=0.0,dd=-.2):
    return dict(session=day,phase=phase,state_sha256='1'*64,input_sha256='2'*64,
        chain_sha256='3'*64,decision=dict(session=day,target_core_exposure=native),
        evidence=dict(observation=dict(session=day,shadow_nav=100,shadow_drawdown=dd,
            shadow_r20=.01,damaged_breadth=.2,green_breadth=.5)),
        economics=dict(last_session=day,strategy_nav='50000',held_allocation=None,
            pending_allocation=str(native),net_factor='1'),comparison_navs=dict(spy='50000'))


class TraceTests(unittest.TestCase):
    def test_prior_overnight_allocation_and_transition_cost_are_load_bearing(self):
        prior=dict(held_allocation='1',pending_allocation='0',parent_core_close_equity='100',strategy_nav='100')
        r=dict(economics=dict(parent_core_open_equity='80',parent_core_close_equity='80',
            strategy_prices=dict(bil_open_adjusted='1',bil_close_adjusted='1',bil_previous_close_adjusted='1')))
        actual=dict(gross_factor='.8',net_factor='.7992',transaction_cost_factor='.999',turnover='1',strategy_nav='79.92')
        s.independent_factor(prior,r,actual)
        for changed in (dict(gross_factor='1'),dict(net_factor='.8'),dict(transaction_cost_factor='1'),
                        dict(turnover='0'),dict(strategy_nav='80')):
            with self.subTest(changed=changed),self.assertRaises(ValueError):
                s.independent_factor(prior,r,{**actual,**changed})

    def test_window_includes_predecessor_close_and_first_loss(self):
        samples=[dict(session=d,B=n,G=n,SPY=n) for d,n in (
            ('2020-12-31','100'),('2021-01-04','80'),('2021-01-05','90'))]
        value=s.metrics(samples,'2021-01-01','2021-12-31')
        self.assertEqual(value['anchor_session'],'2020-12-31')
        self.assertEqual(s.D(value['series']['B']['maximum_drawdown']),s.D('-.2'))
        self.assertEqual(s.D(value['series']['B']['total_return']),s.D('-.1'))

    def test_formation_governor_memory_survives_measurement_anchor(self):
        engine=s.Screen('a'*64)
        engine.consume(row('2008-02-21',phase='FORMATION',native=1.0,dd=-.3),None)
        actual=engine.consume(row(native=1.0,dd=-.2),None)
        self.assertEqual(actual['pending_G'],'0.0')
        self.assertEqual(actual['G'],'50000')
        restored=s.Screen.restore(engine.checkpoint(),'a'*64)
        self.assertEqual(restored.checkpoint(),engine.checkpoint())
        with self.assertRaises(ValueError): s.Screen.restore(engine.checkpoint(),'b'*64)

    def test_anchor_does_not_earn_completed_return(self):
        r=row();r['economics']['strategy_nav']='51000'
        with self.assertRaisesRegex(ValueError,'DAY_ZERO'): s.Screen('a'*64).consume(r,None)

    def test_unavailable_formation_observation_refuses(self):
        r=row();r['evidence']['observation']['shadow_drawdown']=None
        with self.assertRaises(ValueError): s.Screen('a'*64).consume(r,None)

    def test_formed_entry_cannot_reuse_changed_exposure(self):
        engine=s.Screen('a'*64);engine.consume(row(),None)
        engine.accounts['G']['pending_allocation']='.55'
        r=row('2008-02-25');r['economics'].update(initial_deployment=True,held_allocation='0')
        with self.assertRaisesRegex(ValueError,'FORMED_ENTRY_SCOPE'): engine.consume(r,None)

    def test_duplicate_decision_refuses(self):
        engine=s.Screen('a'*64);engine.consume(row(),None)
        with self.assertRaises(ValueError): engine.consume(row(),None)

    def test_screen_request_exact_and_original_protocol_preserved(self):
        path=ROOT/'screen-protocol.json'
        value=dict(schema='research.capital-risk-screen-request/1',request_id='fast-bg-screen-001',
            stage='quick-screen',arms=['B','G'],original_protocol_sha256=s.PROTOCOL,
            screen_protocol_sha256=sha256_file(path))
        validate_request(value,path)
        for change in (dict(arms=['B','C']),dict(extra=True),dict(screen_protocol_sha256='0'*64)):
            with self.assertRaises(ValueError): validate_request({**value,**change},path)

    def test_screen_worker_is_distinct_offline_and_has_no_baseline_cli(self):
        name='capital-risk-bg-screen-123-1'
        self.assertEqual(worker_stage(name),'quick-screen');self.assertEqual(worker_arm(name),'BG')
        with patch('os.getuid',return_value=1001,create=True),patch('os.getgid',return_value=1001,create=True):
            args=screen_command(name,Path('/frozen'),Path('/private'),ROOT)
        self.assertIn('research.arm=BG',args);self.assertIn('research.stage=quick-screen',args)
        self.assertEqual(args[args.index('--network')+1],'none')
        self.assertIn(EXECUTION_IMAGE,args)
        self.assertIn('/driver/trace_screen.py',args)
        self.assertNotIn('--max-transitions',args);self.assertNotIn('--policy',args)
        for bad in ('capital-risk-bg-screen-123-1-old','paper-screen','capital-risk-bg-screen-x-1'):
            with self.assertRaises(ValueError): worker_stage(bad)


if __name__=='__main__': unittest.main()
