"""Pure identity/static orchestration tests; accounts run only on hosted compute."""
from copy import deepcopy
from decimal import Decimal as D
from pathlib import Path
from unittest.mock import patch
import ast,inspect,json,sys,tempfile,unittest
ROOT=Path(__file__).parents[1];sys.path.insert(0,str(ROOT))
import holding_identity as identity
import holding_job as job
from baseline_prefix import worker_stage,worker_arm
from runtime_identity import EXECUTION_IMAGE

class HoldingGuards(unittest.TestCase):
    def fixture(self):
        row=dict(session='2020-11-02',state_sha256='a'*64,input_sha256='b'*64,chain_sha256='c'*64,
            evidence=dict(breadth=dict(holdings=[dict(ticker='SAME',age_sessions=9,own_dd=-.12,r21=-.1,r63=.1),
                dict(ticker='SAME',age_sessions=4,own_dd=-.02,r21=.1,r63=.2)]),
                research_entry_audit=dict(operations=[dict(operation='HOLD_UNCHANGED',slot_id=1,security_id='PERMANENT',ticker='SAME',detail={}),
                    dict(operation='CLOSE_POSITION',slot_id=2,security_id='PERMANENT',ticker='SAME',detail=dict(age=4))])))
        episodes={1:dict(security_id='PERMANENT',signal_session='2020-01-01',shares=D(10),entry_index=1),
            2:dict(security_id='PERMANENT',signal_session='2020-02-01',shares=D(7),entry_index=6)}
        return row,episodes

    def test_duplicate_security_episodes_remain_separate(self):
        row,episodes=self.fixture();observed=identity.bind_observations(row,episodes,row_index=10)
        self.assertEqual(len(observed),2);self.assertEqual([v['shares'] for v in observed],['10','7'])
        self.assertNotEqual(observed[0]['episode'],observed[1]['episode'])
        self.assertEqual(len({v['security_id'] for v in observed}),1)

    def test_identity_never_falls_back_to_matching_ticker(self):
        row,episodes=self.fixture();episodes[1]['security_id']='WRONG'
        with self.assertRaisesRegex(ValueError,'PERMANENT_IDENTITY'):identity.bind_observations(row,episodes,row_index=10)

    def test_review_day_missing_age_uses_exact_filled_entry_index(self):
        row,episodes=self.fixture();identity.bind_observations(row,episodes,row_index=10)
        episodes[1]['entry_index']=2
        with self.assertRaisesRegex(ValueError,'EPISODE_AGE'):identity.bind_observations(row,episodes,row_index=10)

    def test_same_ticker_observation_permutation_is_detected_by_age(self):
        row,episodes=self.fixture();row['evidence']['breadth']['holdings'].reverse()
        with self.assertRaisesRegex(ValueError,'EPISODE_AGE'):identity.bind_observations(row,episodes,row_index=10)

    def test_actual_permanent_identity_guard_removal_accepts_corruption(self):
        source=inspect.getsource(identity.bind_observations)
        broken=source.replace("need(ep['security_id']==operation['security_id'],'REFUSED_PERMANENT_IDENTITY')",
            "need(True,'REFUSED_PERMANENT_IDENTITY')")
        self.assertNotEqual(source,broken);scope=dict(identity.__dict__);exec(compile(broken,'removed-id-guard','exec'),scope)
        row,episodes=self.fixture();episodes[1]['security_id']='FORGED'
        with self.assertRaises(ValueError):identity.bind_observations(row,episodes,row_index=10)
        self.assertEqual(scope['bind_observations'](row,episodes,row_index=10)[0]['security_id'],'FORGED')

    def test_request_exact_source_and_no_performance_scope(self):
        r=job.expected_request();job.validate_request(r)
        for bad in ({**r,'run_full_trial':True},{**r,'qualification_protocol_sha256':'0'*64}):
            with self.assertRaises(ValueError):job.validate_request(bad)

    def test_only_exact_private_names_and_same_offline_fences(self):
        name='capital-risk-holding-qual-123-1'
        self.assertEqual(worker_stage(name),'holding-qualification');self.assertEqual(worker_arm(name),'HOLDING_QUAL')
        for bad in ('paper-holding-qual-123-1',name+'-retry','capital-risk-holding-qual-x-1'):
            with self.assertRaises(ValueError):worker_stage(bad)
        with patch('os.getuid',return_value=1001,create=True),patch('os.getgid',return_value=1001,create=True):
            args=job.command(name,Path('/frozen'),Path('/output'))
        self.assertIn('HOLDING_QUAL_HOSTED=1',args);self.assertIn(EXECUTION_IMAGE,args)
        self.assertEqual(args[args.index('--network')+1],'none');self.assertNotIn('--policy',args)
        self.assertNotIn('--max-transitions',args);self.assertIn('/driver/holding_qualification.py',args)

    def test_real_unknown_and_live_worker_cannot_be_declared_stopped(self):
        name='capital-risk-holding-qual-123-1'
        value=dict(Name='/'+name,Id='1'*64,Image=EXECUTION_IMAGE,
            State=dict(Running=False,Status='exited',ExitCode=0,OOMKilled=False),
            Config=dict(Labels={'research.experiment':'capital-risk-20261027','research.stage':'holding-qualification','research.arm':'HOLDING_QUAL'},
                Env=[],WorkingDir='/fixed',User='1001:1001'),
            HostConfig=dict(NetworkMode='none',ReadonlyRootfs=True,Memory=2*1024**3,MemorySwap=2*1024**3,
                NanoCpus=1000000000,PidsLimit=64,CapDrop=['ALL'],SecurityOpt=['no-new-privileges']),
            Mounts=[dict(Type='bind',Destination=p,RW=p=='/out') for p in ('/frozen','/out','/driver')])
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            path=Path(tmp)/'stop.json';path.write_text(json.dumps(value))
            self.assertEqual(job.stopped(path,name)['exit_code'],0)
            value['State']['Running']=True;path.write_text(json.dumps(value))
            with self.assertRaises(ValueError):job.stopped(path,name)
            with self.assertRaises(ValueError):job.stopped(Path(tmp)/'missing',name)

    def test_account_operations_are_hosted_guarded_and_have_no_core_or_broker_import(self):
        tree=ast.parse((ROOT/'holding_account.py').read_text())
        names={n.name:n for n in tree.body if isinstance(n,ast.FunctionDef)}
        for name in ('trade','mark','split','accrue','pay','cash_merger','snapshot','restore','commit'):
            self.assertIsInstance(names[name].body[0],ast.Expr)
            self.assertEqual(names[name].body[0].value.func.id,'hosted')
        imports=[ast.unparse(n) for n in ast.walk(tree) if isinstance(n,(ast.Import,ast.ImportFrom))]
        self.assertFalse(any(any(s in x for s in ('sentinel','wealth_core','requests','socket','subprocess','psycopg')) for x in imports))

    def test_workflow_is_one_bounded_encrypted_qualification(self):
        text=(ROOT.parents[1]/'.github/workflows/capital-holding-qualification.yml').read_text()
        for required in ('timeout-minutes: 20','github.run_attempt == 1','.github/workflows','retention-days: 7',
                         'holding-qualification.tar.crseal','holding-qualification-request.json'):
            self.assertIn(required,text)
        for forbidden in ('workflow_dispatch:','actions: write','identity-bindings.jsonl','account-cases.json'):
            self.assertNotIn(forbidden,text)
        source=(ROOT/'holding_job.py').read_text();self.assertIn('deadline=180',source)
        self.assertIn('private if known else diagnostic',source)

    def test_canonical_receivable_oracle_is_called_not_compared_as_method(self):
        text=(ROOT/'holding_qualification.py').read_text()
        def all_called(source):
            tree=ast.parse(source)
            methods={id(n) for n in ast.walk(tree) if isinstance(n,ast.Attribute) and n.attr=='receivable_total'}
            calls={id(n.func) for n in ast.walk(tree) if isinstance(n,ast.Call)}
            return bool(methods) and methods<=calls
        self.assertTrue(all_called(text))
        broken=text.replace('ledger.receivable_total()==0','ledger.receivable_total==0')
        self.assertNotEqual(text,broken);self.assertFalse(all_called(broken))

if __name__=='__main__':unittest.main()
