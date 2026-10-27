"""Synthetic tests only. Actual candidate accounts run on hosted compute."""
import json,sys,unittest
from copy import deepcopy
from decimal import Decimal as D
from pathlib import Path

ROOT=Path(__file__).parents[1];sys.path.insert(0,str(ROOT))
from weighted_policy import RiskState,advance,deterioration
from weighted_features import align,feature,make_books
from weighted_screen import Screen,validate_plan,metrics
from weighted_job import validate_request
from baseline_prefix import worker_stage,worker_arm

class RuleTests(unittest.TestCase):
    def go(self,state,day,score,target=1):
        return advance(state,session=day,previous_session=state.last_session,score=score,baseline_target=target)

    def test_entry_threshold_and_never_increase_baseline(self):
        state,target=self.go(RiskState(),'2020-01-02','.299999');self.assertFalse(state.reduced);self.assertEqual(target,1)
        state,target=self.go(state,'2020-01-03','.30');self.assertTrue(state.reduced);self.assertEqual(target,D('.55'))
        state,target=self.go(state,'2020-01-06','.4',0);self.assertEqual(target,0)
        state,target=self.go(state,'2020-01-07','.4','.55');self.assertEqual(target,D('.55'))

    def test_release_uses_three_current_healthy_closes(self):
        state,_=self.go(RiskState(),'2020-01-02','.5')
        for day in ('2020-01-03','2020-01-06'):
            state,target=self.go(state,day,'.15');self.assertTrue(state.reduced);self.assertEqual(target,D('.55'))
        state,target=self.go(state,'2020-01-07','.15');self.assertFalse(state.reduced);self.assertEqual(target,1)

    def test_recovery_streak_resets_without_old_high(self):
        state=RiskState(True,2,'2020-01-02');state,target=self.go(state,'2020-01-03','.16')
        self.assertEqual(state.recovery,0);self.assertTrue(state.reduced)
        self.assertNotIn('drawdown',state.to_dict())

    def test_deterioration_is_and_and_unknown_is_explicit(self):
        self.assertEqual(deterioration('-.10','-.03'),'DETERIORATING')
        self.assertEqual(deterioration('-.20','.05'),'HEALTHY')
        self.assertEqual(deterioration('-.05','-.05'),'HEALTHY')
        self.assertEqual(deterioration(None,'.1'),'UNKNOWN')
        for a,b in ((float('nan'),None),(None,float('inf'))):
            with self.assertRaises(ValueError):deterioration(a,b)

    def test_dates_domains_and_state_refuse(self):
        for score in ('NaN','1.01','-.1'):
            with self.assertRaises(ValueError):self.go(RiskState(),'2020-01-02',score)
        with self.assertRaises(ValueError):advance(RiskState(),session='2020-01-02',previous_session='2020-01-01',score=0,baseline_target=1)
        with self.assertRaises(ValueError):RiskState(False,1,'2020-01-02')
        with self.assertRaises(ValueError):RiskState.restore(dict(reduced=False,recovery=0,last_session=None,extra=True))

    def test_future_observations_do_not_change_prefix(self):
        state=RiskState();prefix=[]
        for day,score in (('2020-01-02','.4'),('2020-01-03','.1')):
            state,target=self.go(state,day,score);prefix.append((state.to_dict(),target))
        saved=deepcopy(prefix)
        for score in ('.1','.9'):
            resumed=RiskState.restore(saved[-1][0]);self.go(resumed,'2020-01-06',score)
            self.assertEqual(prefix,saved)

class FeatureTests(unittest.TestCase):
    def sample(self):
        held=[dict(ticker='TDOC',age_sessions=10,own_dd=-.2,r21=-.05),dict(ticker='TDOC',age_sessions=20,own_dd=-.02,r21=.1)]
        ops=[dict(operation='HOLD_UNCHANGED',slot_id=i,security_id='S',ticker='TDOC',detail=dict(age=h['age_sessions'])) for i,h in enumerate(held)]
        row=dict(session='2020-01-02',state_sha256='a'*64,input_sha256='b'*64,chain_sha256='c'*64,
            economics=dict(parent_core_close_equity='1000'),evidence=dict(breadth=dict(holdings=held),research_entry_audit=dict(operations=ops)))
        return row,dict(shares=dict(S=30),cash=700,claims={}),dict(S='10')

    def test_duplicate_security_counts_capital_once_and_keeps_slots(self):
        row,book,quotes=self.sample();f=feature(row,book,quotes)
        self.assertEqual(D(f['score']),D('.3'));self.assertEqual(f['positions'],1)
        self.assertEqual(f['episodes'],2);self.assertEqual(f['slots'],dict(S=[0,1]))

    def test_unknown_is_scored_not_fabricated(self):
        row,book,quotes=self.sample();row['evidence']['breadth']['holdings'][1]['own_dd']=None
        f=feature(row,book,quotes);self.assertEqual(D(f['unknown_score']),D('.3'));self.assertEqual(f['states']['S'],'UNKNOWN')

    def test_identity_and_age_guard_falsifiers(self):
        row,book,quotes=self.sample();row['evidence']['research_entry_audit']['operations'][0]['security_id']='OTHER'
        with self.assertRaises(ValueError):feature(row,book,quotes)
        row,book,quotes=self.sample();row['evidence']['research_entry_audit']['operations'][0]['detail']['age']=11
        with self.assertRaises(ValueError):feature(row,book,quotes)

    def test_quote_and_equity_refuse(self):
        row,book,quotes=self.sample()
        for bad in ({},{'S':'0'},{'S':'NaN'},{'S':'11'}):
            with self.assertRaises(ValueError):feature(row,book,bad)

    def test_inventory_only_uses_past_events(self):
        rows=[dict(session='2020-01-02'),dict(session='2020-01-03')]
        first=dict(session='2020-01-02',cash_before=50000,cash_after=49900,security_id='S',event_type='BUY',shares_delta=1)
        future=dict(session='2020-01-03',cash_before=49900,cash_after=49999,security_id='S',event_type='SELL',shares_delta=-1)
        self.assertEqual(make_books(rows,[first])['2020-01-02'],make_books(rows,[first,future])['2020-01-02'])

class AuthorityTests(unittest.TestCase):
    def test_frozen_plan_rejects_tuning(self):
        p=json.loads((ROOT/'weighted-screen-protocol.json').read_bytes());validate_plan(p)
        for k,v in [('entry_score','.25'),('release_consecutive_closes',2),('core_financial_changes',True),('parameter_sweep',True)]:
            with self.assertRaises(ValueError):validate_plan({**p,k:v})

    def test_checkpoint_detects_financial_or_authority_changes(self):
        engine=Screen('a'*64);saved=engine.checkpoint();self.assertEqual(Screen.restore(saved,'a'*64).checkpoint(),saved)
        with self.assertRaises(ValueError):Screen.restore(saved,'b'*64)
        changed=deepcopy(saved);changed['completed']=1
        with self.assertRaises(ValueError):Screen.restore(changed,'a'*64)

    def test_metric_anchor_is_previous_close(self):
        rows=[dict(session=d,B=b,R=r,SPY=s) for d,b,r,s in [('2020-01-02','100','100','100'),('2020-01-03','110','108','105'),('2020-01-06','105','109','107')]]
        m=metrics(rows,'2020-01-03','2020-01-06');self.assertEqual(m['anchor_session'],'2020-01-02')
        self.assertEqual(D(m['series']['B']['multiple']),D('1.05'));self.assertEqual(D(m['series']['R']['multiple']),D('1.09'))

    def test_request_and_private_scope(self):
        p=ROOT/'weighted-screen-request.json'
        if not p.exists():self.fail('Versioned weighted request required')
        r=json.loads(p.read_bytes());validate_request(r)
        with self.assertRaises(ValueError):validate_request({**r,'contract_sha256':'0'*64})
        name='capital-risk-br-screen-123-1';self.assertEqual((worker_stage(name),worker_arm(name)),('weighted-screen','BR'))
        with self.assertRaises(ValueError):worker_stage(name+'-fresh-restart')

if __name__=='__main__':unittest.main()
