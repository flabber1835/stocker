"""Pure policy/projection and static financial-boundary tests only."""
from pathlib import Path
from fractions import Fraction as Q
from datetime import date
from unittest.mock import patch
import ast,json,sys,unittest
ROOT=Path(__file__).parents[1];sys.path.insert(0,str(ROOT))
from selective_policy import step,retention
import selective_job as job
import baseline_prefix as prefix

class SelectiveRules(unittest.TestCase):
    def row(self,key='E',sid='S',**kw):
        r=dict(episode=key,security_id=sid,weight='.25',drawdown='.1',red=True,green=False,unknown=False,core_exit=False);r.update(kw);return r
    def test_duplicate_security_capital_aggregates_before_entry(self):
        rows=[self.row('A',weight='.15'),self.row('B',weight='.1')];states={}
        for i in range(5):states,changes,_=step(states,rows)
        self.assertTrue(all(s['active'] for s in states.values()));self.assertEqual(len(changes),2)
        states={}
        for i in range(5):states,_,_=step(states,[rows[0],{**rows[1],'security_id':'OTHER'}])
        self.assertFalse(any(s['active'] for s in states.values()))
    def test_five_entry_closes_and_eight_recovery_closes(self):
        states={}
        for i in range(4):states,changes,_=step(states,[self.row()]);self.assertFalse(changes)
        states,changes,_=step(states,[self.row()]);self.assertEqual(retention(states,'E'),Q('.55'))
        for i in range(7):states,changes,_=step(states,[self.row(red=False,green=True)]);self.assertFalse(changes)
        states,changes,_=step(states,[self.row(red=False,green=True)]);self.assertEqual(retention(states,'E'),1)
    def test_unknown_resets_counters_and_preserves_active(self):
        state={'E':dict(active=True,entry=0,recovery=7)}
        state,changes,_=step(state,[self.row(unknown=True,green=True)]);self.assertEqual(state['E'],dict(active=True,entry=0,recovery=0));self.assertFalse(changes)
        state={'E':dict(active=False,entry=4,recovery=0)}
        state,changes,_=step(state,[self.row(unknown=True)]);self.assertFalse(state['E']['active']);self.assertEqual(state['E']['entry'],0)
    def test_core_exit_dominates_and_disabled_cannot_activate(self):
        state={'E':dict(active=True,entry=0,recovery=7)}
        result,changes,_=step(state,[self.row(core_exit=True,green=True)]);self.assertEqual(result,{})
        result,changes,_=step(state,[self.row()],enabled=False);self.assertFalse(result['E']['active']);self.assertFalse(changes)
    def test_wrong_episode_or_negative_risk_refuses(self):
        with self.assertRaises(ValueError):step({},[self.row(),self.row()])
        with self.assertRaises(ValueError):step({},[self.row(weight='-.1')])
    def test_actual_own_red_gate_removal_changes_behavior(self):
        text=(ROOT/'selective_policy.py').read_text();broken=text.replace("if r['red'] and not r['unknown']:","if not r['unknown']:").replace("r['red'] and score>=Q('0.02')","score>=Q('0.02')")
        self.assertNotEqual(text,broken);scope={};exec(compile(broken,'removed-own-red','exec'),scope)
        left=right={};rows=[self.row(red=False)]
        for i in range(5):left,_,_=step(left,rows);right,_,_=scope['step'](right,rows)
        self.assertFalse(left['E']['active']);self.assertTrue(right['E']['active'])
    def projection(self):
        tree=ast.parse((ROOT/'selective_model.py').read_text());node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='project')
        env=dict(Q=Q,retention=retention,need=lambda v,c:None if v else (_ for _ in ()).throw(ValueError(c)))
        exec(compile(ast.Module(body=[node],type_ignores=[]),'pure-close-projection','exec'),env);return env['project']
    def test_unchanged_global_and_local_states_never_resize(self):
        f=dict(row=dict(session='2025-01-02',state_sha256='a',input_sha256='b',chain_sha256='c',economics=dict(pending_allocation='1',parent_core_close_equity='1000'),
            evidence=dict(research_entry_audit=dict(operations=[]))),holdings=[dict(episode='E',security_id='S',slot_id=0,shares='20',source_observation=dict(ticker='S'))],prices={'S':dict(raw_close='10')})
        result=self.projection()(f,Q(2000),{},[],'1');self.assertEqual(result['targets'],{})
        result=self.projection()(f,Q(2000),{'E':dict(active=True)},[dict(episode='E',transition='ENTER')],'1')
        self.assertEqual(Q(result['targets']['E']['dollars']),220);self.assertEqual(result['targets']['E']['cause'],'LOCAL_ENTER')
    def test_exact_request_and_offline_additional_readonly_mount(self):
        r=job.expected_request();job.validate_request(r)
        with self.assertRaises(ValueError):job.validate_request({**r,'owner_scope':'sweep'})
        with patch('os.getuid',return_value=1001,create=True),patch('os.getgid',return_value=1001,create=True):
            args=job.command('capital-risk-h0p2-123-1',Path('/frozen'),Path('/qualified'),Path('/output'))
        self.assertIn(f'type=bind,source={Path("/qualified")},target=/qualified,readonly',args);self.assertEqual(args[args.index('--network')+1],'none')
    def test_no_local_run_or_core_replay_and_strict_baseline_gate(self):
        text=(ROOT/'selective_screen.py').read_text()
        for v in ('REFUSED_LOCAL_H0_P2','REFUSED_MATCHED_DISABLED_CONTROL','REFUSED_P2_SERIALIZED_SUFFIX','REFUSED_BASELINE_READINESS_BUDGET'):self.assertIn(v,text)
        self.assertLess(text.index('REFUSED_MATCHED_DISABLED_CONTROL'),text.index("a.output/'P2'"))
        self.assertNotIn('run_module(',text);self.assertNotIn('research_config(',text)
    def test_historical_source_and_prices_are_exactly_admitted(self):
        text=(ROOT/'selective_job.py').read_text()
        for v in ('REFUSED_QUAL_RECEIPT_BYTES','REFUSED_QUAL_CIPHER','REFUSED_CHANGED_QUALIFIED_ACCOUNT','private if known else diagnostic'):
            self.assertIn(v,text)
        text=(ROOT/'selective_input.py').read_text();self.assertIn('REFUSED_P2_QUALIFIED_PRICE_FILE',text)
    def test_workflow_is_bounded_encrypted_and_has_no_plaintext_financial_upload(self):
        text=(ROOT.parents[1]/'.github/workflows/capital-selective-h0-p2.yml').read_text()
        for v in ('timeout-minutes: 20','timeout-minutes: 9','retention-days: 7','actions: read','github.run_attempt == 1','selective-comparison.tar.crseal'):self.assertIn(v,text)
        for v in ('workflow_dispatch:','contents: write','events.jsonl','checkpoint.json.gz'):self.assertNotIn(v,text)

    def test_actual_launcher_fourth_mount_admission_and_original_failure_falsifier(self):
        import inspect
        fixture=dict(HostConfig=dict(NetworkMode='none',ReadonlyRootfs=True,Memory=2*1024**3,MemorySwap=2*1024**3,
            NanoCpus=1000000000,PidsLimit=64,CapDrop=['ALL'],SecurityOpt=['no-new-privileges']),
            Config=dict(WorkingDir='/fixed',User='1001:1001',Env=[]),
            Mounts=[dict(Type='bind',Destination=p,RW=p=='/out') for p in ('/frozen','/out','/driver','/qualified')])
        name='capital-risk-h0p2-proof-123-1'
        with patch.object(prefix,'identity_inspect',return_value=fixture),patch('os.getuid',return_value=1001,create=True),patch('os.getgid',return_value=1001,create=True):
            self.assertEqual(prefix.fenced_inspect(name),fixture)
            fixture['Mounts'][-1]['RW']=True
            with self.assertRaises(ValueError):prefix.fenced_inspect(name)
            fixture['Mounts'][-1]['RW']=False
            text=inspect.getsource(prefix.fenced_inspect);broken=text.replace("|({'/qualified'} if qualified else set())",'')
            self.assertNotEqual(text,broken);scope=dict(prefix.__dict__);exec(compile(broken,'original-omitted-qualified-mount','exec'),scope)
            with self.assertRaisesRegex(ValueError,'MOUNTS'):scope['fenced_inspect'](name)

if __name__=='__main__':unittest.main()
