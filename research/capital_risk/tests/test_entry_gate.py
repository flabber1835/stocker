"""Pure/static safeguards; real canonical state/account qualification is hosted."""
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
import hashlib,inspect,json,sys,tempfile,unittest
ROOT=Path(__file__).parents[1];sys.path.insert(0,str(ROOT))
import entry_gate_policy as policy
import entry_gate_screen as screen
import entry_gate_job as job
from baseline_prefix import worker_stage,worker_arm
from runtime_identity import EXECUTION_IMAGE
from screen_job import encrypt


class Model:
    def __init__(self,value):self.value=value
    def model_dump(self):return self.value


class Fake:
    """Synthetic cursor fixture, not the canonical Owned55 implementation."""
    STRATEGY_ID='synthetic'
    @staticmethod
    def fresh():return dict(last_session=None)
    @staticmethod
    def validate(identity,state,expected_session):
        if state['last_session']!=expected_session:raise ValueError('cursor')
        return Model(state)
    @staticmethod
    def step(observation,base_target,state):
        return dict(last_session=observation.session),dict(target=base_target)


class EntryGateGuards(unittest.TestCase):
    def source(self):return b'RULE = dict(entry_damage=.88, recovery_damage=.63)\n'

    def test_variant_source_changes_only_one_literal_and_preserves_original(self):
        source=self.source();h=hashlib.sha256(source).hexdigest()
        changed=policy.variant_source(source,h)
        self.assertEqual(changed,b'RULE = dict(entry_damage=.75, recovery_damage=.63)\n')
        self.assertEqual(source,self.source())
        for raw,expected in [(source,'0'*64),(source+source,hashlib.sha256(source+source).hexdigest())]:
            with self.assertRaises(ValueError):policy.variant_source(raw,expected)

    def test_actual_source_hash_guard_removal_is_detectable(self):
        source=inspect.getsource(policy.variant_source)
        mutated=source.replace("require(hashlib.sha256(raw).hexdigest()==expected_sha,'REFUSED_ENTRY_SOURCE_BYTES')",
            "require(True,'REFUSED_ENTRY_SOURCE_BYTES')")
        self.assertNotEqual(source,mutated);scope=dict(policy.__dict__)
        exec(compile(mutated,'removed-entry-source-guard','exec'),scope)
        with self.assertRaises(ValueError):policy.variant_source(self.source(),'0'*64)
        self.assertEqual(scope['variant_source'](self.source(),'0'*64),self.source().replace(b'.88',b'.75'))

    def test_reused_watch_proof_must_bind_exact_original_file_and_commitments(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            root=Path(tmp);raw=b'original exact gzip bytes';(root/'checkpoint.json.gz').write_bytes(raw)
            cp=dict(sha256='a'*64,run=dict(checkpoint_sha256='b'*64),
                journals={name:dict(bytes=0,prefix_sha256='c'*64,last_record_sha256=None)
                    for name in ('formation','daily','monthly','watch')})
            proof=dict(status='INDEPENDENT_COMPLETION_REVIEW_PASSED',arm='fixed',canonical_roundtrip=True,
                all_historical_prefixes_verified=True,full_chain_verified=True,
                final_file_sha256=hashlib.sha256(raw).hexdigest(),final_outer=cp['sha256'],
                final_inner=cp['run']['checkpoint_sha256'],journal_commitments=cp['journals'])
            (root/'fixed-review.json').write_text(json.dumps(proof))
            self.assertIn('REUSED',screen.admit_completion_lineage(root,cp)['watch_proof'])
            bad=deepcopy(cp);bad['journals']['watch']['bytes']=1
            with self.assertRaises(ValueError):screen.admit_completion_lineage(root,bad)
            (root/'checkpoint.json.gz').write_bytes(raw+b'changed')
            with self.assertRaises(ValueError):screen.admit_completion_lineage(root,cp)

    def test_entire_protocol_is_frozen_not_only_damage_parameter(self):
        plan=json.loads((ROOT/'entry-gate-protocol.json').read_bytes());screen.validate_plan(plan)
        for key,value in [('entry_green','0.10'),('recovery_confirmations',3),('candidate_damage','0.74'),
            ('automatic_extension',True),('production_contacted',True),('job_timeout_minutes',40)]:
            with self.subTest(key=key),self.assertRaises(ValueError):screen.validate_plan({**plan,key:value})

    def test_day_zero_does_not_earn_past_returns_or_change_funding(self):
        row=dict(session=screen.START,economics=dict(strategy_nav='50000',held_allocation=None,
            pending_allocation='0',net_factor='1'))
        self.assertEqual(screen.initial_account(None,row,0.0,0),row['economics'])
        for target in (.55,1):
            with self.assertRaisesRegex(ValueError,'ANCHOR'):screen.initial_account(None,row,target,0)
        row['economics']['strategy_nav']='50001'
        with self.assertRaises(ValueError):screen.initial_account(None,row,0,0)

    def test_all_cash_formed_startup_validates_real_cost_before_copy(self):
        prior=dict(held_allocation=None,pending_allocation='0')
        row=dict(economics=dict(initial_deployment=True,held_allocation='0',pending_allocation='0',
            net_factor='.999',strategy_nav='49950',strategy_prices=dict(bil_close_adjusted='1',bil_open_adjusted='1')))
        self.assertEqual(screen.initial_account(prior,row,0.,1),row['economics'])
        for change in [dict(pending_allocation='.55'),dict(held_allocation='0')]:
            with self.assertRaises(ValueError):screen.initial_account({**prior,**change},row,0,1)
        row['economics']['net_factor']='1'
        with self.assertRaises(ValueError):screen.initial_account(prior,row,0,1)

    def test_policy_checks_exact_recorded_baseline_and_duplicate_cursor(self):
        engine=policy.Policies(Fake,Fake)
        row=dict(session='2020-01-02',decision=dict(session='2020-01-02',champion_target_core_exposure=1.,
            target_core_exposure=1.,owned_impairment=dict(target=1.)),
            evidence=dict(observation=dict(session='2020-01-02')))
        engine.step(row)
        with self.assertRaises(ValueError):engine.step(row)
        bad=deepcopy(row);bad['session']=bad['decision']['session']=bad['evidence']['observation']['session']='2020-01-03'
        bad['decision']['owned_impairment']['target']=.55
        with self.assertRaisesRegex(ValueError,'CONTROL_POLICY'):engine.step(bad)

    def test_serialized_account_policy_state_cannot_change_contract_or_cursor(self):
        e=screen.Screen('a'*64,Fake,Fake);e.policies.states=[dict(last_session='2020-12-31')]*2
        e.policies.last_session='2020-12-31';e.completed=1
        e.accounts={arm:dict(strategy_nav='50000',last_session='2020-12-31') for arm in ('B','E75')}
        saved=e.checkpoint()
        self.assertEqual(screen.Screen.restore(saved,'a'*64,Fake,Fake).checkpoint(),saved)
        with self.assertRaises(ValueError):screen.Screen.restore(saved,'b'*64,Fake,Fake)
        bad=deepcopy(saved);bad['accounts']['E75']['strategy_nav']='1'
        with self.assertRaises(ValueError):screen.Screen.restore(bad,'a'*64,Fake,Fake)

    def test_window_accounts_for_first_loss_using_previous_close(self):
        samples=[dict(session=day,B=nav,E75=nav,SPY=nav) for day,nav in [
            ('2020-12-31','100'),('2021-01-04','80'),('2021-01-05','90')]]
        result=screen.metric(samples,'2021-01-01','2021-12-31')
        self.assertEqual(result['anchor_session'],'2020-12-31')
        self.assertEqual(screen.D(result['series']['E75']['maximum_drawdown']),screen.D('-.2'))
        exact=screen.metric(samples,'2021-01-04','2021-01-05',anchor_at_first=True)
        self.assertEqual(exact['anchor_session'],'2021-01-04')
        self.assertEqual(screen.D(exact['series']['E75']['total_return']),screen.D('.125'))

    def test_new_worker_is_exact_fenced_and_has_no_Core_replay_arguments(self):
        name='capital-risk-entry75-123-1'
        self.assertEqual(worker_stage(name),'entry-gate-screen');self.assertEqual(worker_arm(name),'BE75')
        with patch('os.getuid',return_value=1001,create=True),patch('os.getgid',return_value=1001,create=True):
            args=job.command(name,Path('/frozen'),Path('/out'))
        self.assertIn('OWNED55_ENTRY_HOSTED=1',args);self.assertIn('research.arm=BE75',args)
        self.assertEqual(args[args.index('--network')+1],'none');self.assertIn(EXECUTION_IMAGE,args)
        self.assertNotIn('--policy',args);self.assertNotIn('--max-transitions',args)
        for bad in ('paper-entry75-123-1',name+'-retry','capital-risk-entry75-x-1'):
            with self.assertRaises(ValueError):worker_stage(bad)

    def test_exact_request_rejects_extra_or_changed_source(self):
        request=job.expected_request();job.validate_request(request)
        for changed in [{**request,'extra':True},{**request,'contract_sha256':'0'*64}]:
            with self.assertRaises(ValueError):job.validate_request(changed)

    def test_financial_entrypoint_refuses_local_context_before_canonical_import(self):
        with patch.dict('os.environ',{},clear=True),self.assertRaisesRegex(ValueError,'LOCAL_FINANCIAL'):
            screen.run(Path('/not-opened'),Path('/not-created'),ROOT/'entry-gate-protocol.json')

    def test_unknown_or_live_worker_never_becomes_a_saved_stop(self):
        name='capital-risk-entry75-123-1'
        value=dict(Name='/'+name,Id='1'*64,Image=EXECUTION_IMAGE,
            State=dict(Running=False,Status='exited',ExitCode=1,OOMKilled=False),
            Config=dict(Labels={'research.experiment':'capital-risk-20261027','research.stage':'entry-gate-screen','research.arm':'BE75'},
                Env=[],WorkingDir='/fixed',User='1001:1001'),
            HostConfig=dict(NetworkMode='none',ReadonlyRootfs=True,Memory=2*1024**3,MemorySwap=2*1024**3,
                NanoCpus=1000000000,PidsLimit=64,CapDrop=['ALL'],SecurityOpt=['no-new-privileges']),
            Mounts=[dict(Type='bind',Destination=p,RW=p=='/out') for p in ['/frozen','/out','/driver']])
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            path=Path(tmp)/'stop.json';path.write_text(json.dumps(value))
            self.assertEqual(job.saved_stop(path,name)['exit_code'],1)
            value['State']['OOMKilled']=True;path.write_text(json.dumps(value));self.assertTrue(job.saved_stop(path,name)['oom'])
            value['State']['Running']=True;path.write_text(json.dumps(value))
            with self.assertRaises(ValueError):job.saved_stop(path,name)
            with self.assertRaises(ValueError):job.saved_stop(Path(tmp)/'missing',name)

    def test_workflow_one_run_budget_secret_and_encrypted_artifacts(self):
        text=(ROOT.parents[1]/'.github/workflows/capital-owned55-entry-gate.yml').read_text()
        self.assertIn('timeout-minutes: 20',text);self.assertIn('github.run_attempt == 1',text)
        self.assertIn('retention-days: 7',text);self.assertIn('entry-gate.tar.crseal',text)
        self.assertIn('            .github/workflows\n',text)
        self.assertNotIn('workflow_dispatch:',text);self.assertNotIn('actions: write',text)
        self.assertNotIn('daily.jsonl',text);self.assertNotIn('checkpoint.json',text)
        self.assertIn('paths:',text);self.assertIn('entry-gate-request.json',text)
        source=(ROOT/'entry_gate_screen.py').read_text()
        self.assertLess(source.index("if not any(window_coverage.values()):"),source.index('engine=Screen(contract'))


if __name__=='__main__':unittest.main()
