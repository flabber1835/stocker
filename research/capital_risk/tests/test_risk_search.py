"""Pure policy/metric/static search tests; no funded Runtime/Core execution."""
from pathlib import Path
from fractions import Fraction as Q
from collections import Counter
from copy import deepcopy
from unittest.mock import patch
import ast,json,sys,unittest
ROOT=Path(__file__).parents[1];sys.path.insert(0,str(ROOT))
from risk_profiles import profiles,selected,Profile
from risk_policy import step,retention,projection
from risk_metrics import metrics,windows,development_record,rank
from risk_review_math import check_profile_policy,bounded_fee_statistic
import risk_search_job as job
from risk_review import event_view
from risk_review_math import digest

class RiskSearchTests(unittest.TestCase):
    def obs(self,key='E',sid='S',**kw):
        value=dict(episode=key,security_id=sid,weight='.2',drawdown='.25',red=True,green=False,unknown=False,core_exit=False,source_state_sha256='a'*64);value.update(kw);return value

    def test_exact_twelve_and_no_unregistered_profile(self):
        values=profiles();self.assertEqual(len(values),12);self.assertEqual(len({p.id for p in values}),12)
        self.assertEqual(Counter(p.family for p in values),{'LOCAL_RED':4,'BOOK_DAMAGE':4,'CONCENTRATION_BAND':4})
        with self.assertRaises(ValueError):selected('ONE_MORE_SEARCH_TRIAL')
        with self.assertRaises(ValueError):Profile(id='BAD',family='LOCAL_RED',entry=1,recovery=3,retained='-1')

    def test_local_three_confirms_without_capital_filter_and_recovery(self):
        p=selected('L3_KEEP55');s={};row=self.obs(weight='.001')
        for i in range(2):s,c,_=step(p,s,[row]);self.assertFalse(c)
        s,c,_=step(p,s,[row]);self.assertTrue(s['E']['active']);self.assertEqual(retention(p,s,'E'),Q('.55'))
        for i in range(3):s,c,_=step(p,s,[{**row,'red':False,'green':True}])
        self.assertFalse(s['E']['active']);self.assertEqual(c[0]['transition'],'RECOVER')

    def test_zero_retention_and_unknown_do_not_restore(self):
        p=selected('L1_KEEP0');s,_,_=step(p,{},[self.obs()]);self.assertEqual(retention(p,s,'E'),0)
        s,c,_=step(p,s,[self.obs(unknown=True,green=True)]);self.assertTrue(s['E']['active']);self.assertFalse(c)

    def test_book_aggregates_loss_and_preserves_unknown(self):
        p=selected('B04_C1');rows=[self.obs('A','A',weight='.2',drawdown='.1'),self.obs('B','B',weight='.2',drawdown='.1')]
        s,c,proof=step(p,{},rows);self.assertTrue(s['__book__']['active']);self.assertEqual(len(c),2);self.assertEqual(Q(proof['book']['impairment']),Q('.04'))
        s,c,_=step(p,s,[{**rows[0],'unknown':True},rows[1]]);self.assertTrue(s['__book__']['active']);self.assertFalse(c)
        for i in range(3):s,c,_=step(p,s,[{**r,'red':False,'green':True} for r in rows])
        self.assertFalse(s['__book__']['active'])

    def test_cap_aggregates_duplicate_sid_and_rebalances_at_21(self):
        p=selected('C15_C1');rows=[self.obs('A',weight='.08'),self.obs('B',weight='.08')];s,c,_=step(p,{},rows)
        self.assertEqual(len(c),2);self.assertEqual(retention(p,s,'A'),Q('.75'));self.assertEqual(s['A'],s['B'])
        for i in range(20):s,c,_=step(p,s,rows);self.assertFalse(c)
        s,c,_=step(p,s,rows);self.assertEqual(len(c),2);self.assertEqual(s['A']['age'],0)
        for i in range(3):s,c,_=step(p,s,[{**r,'weight':'.05'} for r in rows])
        self.assertFalse(s['A']['active']);self.assertEqual(retention(p,s,'A'),1)

    def test_cap_is_strict_and_own_metrics_not_required(self):
        p=selected('C15_C1');s,c,_=step(p,{},[self.obs(weight='.15',unknown=True)]);self.assertFalse(c)
        s,c,_=step(p,s,[self.obs(weight='.16',unknown=True)]);self.assertTrue(c)

    def test_core_exit_dominates_every_family(self):
        for p in profiles():
            s={}
            for i in range(4):s,_,_=step(p,s,[self.obs(weight='.5')])
            s,c,proof=step(p,s,[self.obs(weight='.5',core_exit=True)]);self.assertNotIn('E',s);self.assertFalse(c)

    def test_independent_policy_equations_all_profiles(self):
        for p in profiles():
            state={}
            for i in range(32):
                green=i>=25;observations=[self.obs(weight='.05' if green else '.3',red=not green,green=green,drawdown='.01' if green else '.25')]
                actual,changes,audit=step(p,state,observations);expected,expected_changes=check_profile_policy(observations,audit,state,p,'a'*64)
                self.assertEqual(actual,expected);self.assertEqual(changes,expected_changes);state=actual

    def test_actual_red_guard_removal_falsifier(self):
        source=(ROOT/'risk_policy.py').read_text();changed=source.replace("if r['red'] else 0","if True else 0");self.assertNotEqual(source,changed)
        scope={};exec(compile(changed,'risk-red-guard-removed','exec'),scope);p=selected('L1_KEEP55');row=self.obs(red=False)
        good,_,_=step(p,{},[row]);bad,_,_=scope['step'](p,{},[row]);self.assertFalse(good['E']['active']);self.assertTrue(bad['E']['active'])

    def original_projection(self,p):
        node=next(n for n in ast.parse((ROOT/'selective_model.py').read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='project')
        env=dict(Q=Q,retention=lambda states,key:retention(p,states,key),need=lambda v,c:None if v else (_ for _ in ()).throw(ValueError(c)))
        exec(compile(ast.Module(body=[node],type_ignores=[]),'qualified-pure-projection','exec'),env);return env['project']

    def test_book_projection_once_and_new_entries_and_no_frame_mutation(self):
        p=selected('B02_C1');frame=dict(row=dict(session='2020-01-02',state_sha256='a',input_sha256='b',chain_sha256='c',economics=dict(pending_allocation='1',parent_core_close_equity='1000'),evidence=dict(research_entry_audit=dict(operations=[dict(operation='OPEN_SLOT_POSITION',slot_id=1,security_id='T',ticker='T',detail=dict(target_weight='.05'))]))),holdings=[dict(episode='E',security_id='S',slot_id=0,shares='20',source_observation=dict(ticker='S'))],prices={'S':dict(raw_close='10')})
        before=deepcopy(frame);out=projection(p,self.original_projection(p),frame,Q(1000),{'__book__':dict(active=True)},[],'1')
        self.assertEqual(frame,before);self.assertEqual(Q(out['global_target']),Q('.55'));self.assertEqual(Q(out['targets']['E']['dollars']),110)
        self.assertEqual(Q(out['targets']['E']['neutral_dollars']),200);self.assertEqual(Q(out['targets']['2020-01-02/1']['dollars']),Q('27.5'))
        self.assertTrue(out['targets']['2020-01-02/1']['local_active'])

    def test_metrics_and_selector_never_accept_validation_fields(self):
        baseline=windows([('2008-02-22','100'),('2012-12-31','200'),('2017-12-29','400'),('2022-12-30','500'),('2026-07-31','600')])
        p=selected('L1_KEEP55');r=development_record(p,baseline,baseline,Q('.01'),True);r['review_passed']=True
        self.assertEqual(rank([r])['selected'],[p.id]);bad=deepcopy(r);bad['metrics']['validation_0']=baseline['validation_0']
        with self.assertRaisesRegex(ValueError,'VALIDATION_LEAK'):rank([bad])
        bad=deepcopy(r);bad['ranking_loss']=-999
        with self.assertRaisesRegex(ValueError,'SCORE'):rank([bad])

    def test_worker_and_review_are_hosted_and_bind_profile(self):
        text=(ROOT/'risk_worker.py').read_text();self.assertIn('REFUSED_LOCAL_RISK_SEARCH',text);self.assertIn('REFUSED_SEARCH_RESTORE_FALSIFIER',text)
        adapter=(ROOT/'risk_adapter.py').read_text();self.assertIn("profile.model_dump(mode='json')",adapter);self.assertIn('REFUSED_LOCAL_SEARCH_RUNTIME',adapter)
        reviewer=(ROOT/'risk_review.py').read_text();self.assertNotIn('import risk_policy',reviewer);self.assertNotIn('import selective_model',reviewer)

    def test_exact_request_original_basis_and_closed_budget(self):
        request=job.expected_request();job.validate_request(request)
        with self.assertRaises(ValueError):job.validate_request({**request,'worker_seconds':9999})
        text=(ROOT.parents[1]/'.github/workflows/capital-bounded-risk-search.yml').read_text()
        for v in ('timeout-minutes: 90','timeout-minutes: 65','retention-days: 7','contents: read','github.run_attempt == 1'):self.assertIn(v,text)
        for v in ('contents: write','workflow_dispatch:','checkpoint.json.gz','daily.jsonl.gz'):self.assertNotIn(v,text)

    def hash_fixture(self,source):
        before=dict(source_sha256=source,chain_sha256='0'*64,fixed='synthetic-hash-only-marker')
        terms=dict(predecessor_sha256=digest(before),ratio='1',cash_per_share='0')
        event=dict(terms=terms,terms_sha256=digest(terms),operation='CONVERSION')
        record=dict(event=event,state_without_chain=dict(source_sha256=source,fixed='same-marker'))
        chain=digest(dict(previous=before['chain_sha256'],record=record));return before,dict(record={**record,'chain_sha256':chain},context={})

    def test_bound_action_identity_is_strict_default_and_narrow_opt_in(self):
        a,left=self.hash_fixture('a'*64);b,right=self.hash_fixture('b'*64)
        self.assertNotEqual(event_view(left,a,'a'*64)[0],event_view(right,b,'b'*64)[0])
        self.assertEqual(event_view(left,a,'a'*64,True)[0],event_view(right,b,'b'*64,True)[0])
        bad=deepcopy(right);bad['record']['event']['terms']['ratio']='2';bad['record']['event']['terms_sha256']=digest(bad['record']['event']['terms']);bad['record']['chain_sha256']=digest(dict(previous=b['chain_sha256'],record={k:v for k,v in bad['record'].items() if k!='chain_sha256'}))
        self.assertNotEqual(event_view(left,a,'a'*64,True)[0],event_view(bad,b,'b'*64,True)[0])

    def test_actual_predecessor_guard_removal_falsifier(self):
        before,observed=self.hash_fixture('a'*64);bad=deepcopy(observed);bad['record']['event']['terms']['predecessor_sha256']='0'*64;bad['record']['event']['terms_sha256']=digest(bad['record']['event']['terms']);bad['record']['chain_sha256']=digest(dict(previous=before['chain_sha256'],record={k:v for k,v in bad['record'].items() if k!='chain_sha256'}))
        with self.assertRaisesRegex(ValueError,'OWN_BOUND_ACTION'):event_view(bad,before,'a'*64,True)
        import risk_review
        node=next(n for n in ast.parse((ROOT/'risk_review.py').read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='event_view')
        class Remove(ast.NodeTransformer):
            def visit_Expr(self,n):
                if isinstance(n.value,ast.Call) and n.value.args and isinstance(n.value.args[-1],ast.Constant) and n.value.args[-1].value=='ORACLE_OWN_BOUND_ACTION_DIGESTS':return None
                return n
        tree=Remove().visit(ast.Module(body=[node],type_ignores=[]));ast.fix_missing_locations(tree);scope=dict(risk_review.__dict__);exec(compile(tree,'removed-own-action-predecessor-guard','exec'),scope);scope['event_view'](bad,before,'a'*64,True)

    def test_fee_statistic_is_bounded_without_relaxing_python_guard(self):
        value=Q(0);exact=Q(0)
        for n in range(1000,1500):
            term=Q(1,n*10000019+7);value+=bounded_fee_statistic(term);exact+=term
        self.assertLess(len(str(value)),100);self.assertLessEqual(abs(value-exact),500*Q('5e-37'))

if __name__=='__main__':unittest.main()
