"""Completion admission/orchestration guards; no financial account execution."""
from pathlib import Path
from unittest.mock import patch
import ast,hashlib,json,sys,tempfile,unittest
ROOT=Path(__file__).parents[1];sys.path.insert(0,str(ROOT))
import selective_completion_job as job

class CompletionGuards(unittest.TestCase):
    def test_exact_request_and_original_65_driver_bytes(self):
        request=job.expected_request();basis=job.validate_request(request)
        self.assertEqual(len(basis['original_drivers']),65)
        with self.assertRaises(ValueError):job.validate_request({**request,'worker_deadline_seconds':60})
        with patch.object(job,'sha256_file',side_effect=lambda p:'0'*64 if p.name=='selective_model.py' else hashlib.sha256(p.read_bytes()).hexdigest()):
            with self.assertRaisesRegex(ValueError,'CHANGED_FINANCIAL'):job.validate_request(request)

    def test_four_mounts_unchanged_and_only_missing_worker_entrypoint(self):
        with patch('os.getuid',return_value=1001,create=True),patch('os.getgid',return_value=1001,create=True):
            argv=job.command('capital-risk-h0p2-123-1',Path('/frozen'),Path('/qualified'),Path('/out'))
        self.assertEqual(argv.count('--mount'),4);self.assertIn('/driver/selective_completion.py',argv)
        self.assertIn(f'type=bind,source={Path("/qualified")},target=/qualified,readonly',argv)
        self.assertEqual(argv[argv.index('--network')+1],'none');self.assertIn('/qualified/controls',argv)

    def test_no_neutral_replay_or_financial_source_rewrite(self):
        text=(ROOT/'selective_completion.py').read_text();tree=ast.parse(text)
        calls=[n for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='run_book']
        self.assertEqual(len(calls),2)
        self.assertIn("enabled=True)",text);self.assertIn("boundary=boundary,checkpoints=False",text)
        for guard in ('REFUSED_CHANGED_FINANCIAL_SOURCE_IDENTITY','REFUSED_COMPLETION_SERIALIZED_SUFFIX','REFUSED_CHANGED_EPISODE_BINDINGS','REFUSED_COMPLETION_BOUNDARY_OR_PRIOR_P2'):
            self.assertIn(guard,text)
        self.assertNotIn('REFUSED_BASELINE_READINESS_BUDGET',text)
        self.assertNotIn('run_module(',text);self.assertNotIn('model_copy(',text)

    def admission_fixture(self,different_path=False):
        tree=ast.parse((ROOT/'selective_completion.py').read_bytes());node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='admitted_controls')
        fn=ast.Module(body=[node],type_ignores=[]);need=lambda v,c:None if v else (_ for _ in ()).throw(ValueError(c))
        def restore(path,source,canonical,enabled):return dict(runtime=dict(policy_enabled=enabled,session='2020-12-31' if 'restart' in path.name else '2026-07-31',fixed='fixed-synthetic-marker'))
        with tempfile.TemporaryDirectory(dir=ROOT) as temp:
            p=Path(temp)
            for arm,sha in [('H0','a'*64),('H0-disabled',('b' if different_path else 'a')*64)]:
                out=p/'comparison'/arm;out.mkdir(parents=True);(out/'book-summary.json').write_text(json.dumps(dict(records=4639,last_session='2026-07-31',finance_path_sha256=sha,events={'fixed':'synthetic-marker'})))
            scope=dict(json=json,restore_exact=restore,need=need,BOUNDARY='2020-12-31');exec(compile(fn,'actual-admission-function','exec'),scope)
            if not different_path:return scope['admitted_controls'](p,'f'*64,{})
            with self.assertRaisesRegex(ValueError,'CONTROL_PATH'):scope['admitted_controls'](p,'f'*64,{})
            class RemoveOnlyPathGuard(ast.NodeTransformer):
                def visit_Expr(self,n):
                    if isinstance(n.value,ast.Call) and isinstance(n.value.func,ast.Name) and n.value.func.id=='need' and isinstance(n.value.args[-1],ast.Constant) and n.value.args[-1].value=='REFUSED_COMPLETION_CONTROL_PATH':return None
                    return n
            mutated=RemoveOnlyPathGuard().visit(fn);ast.fix_missing_locations(mutated);exec(compile(mutated,'removed-path-guard','exec'),scope)
            # The exact real guard rejects unequal financial paths; its removal admits them.
            scope['admitted_controls'](p,'f'*64,{})

    def test_actual_control_path_guard_and_removal_falsifier(self):
        self.admission_fixture();self.admission_fixture(different_path=True)

    def test_artifact_and_workflow_no_public_financial_plaintext(self):
        text=(ROOT.parents[1]/'.github/workflows/capital-selective-completion.yml').read_text()
        for s in ('timeout-minutes: 30','timeout-minutes: 12','retention-days: 7','github.run_attempt == 1','selective-completion.tar.crseal'):
            self.assertIn(s,text)
        for s in ('contents: write','workflow_dispatch:','daily.jsonl.gz','checkpoint.json.gz'):
            self.assertNotIn(s,text)
        source=(ROOT/'selective_completion_job.py').read_text()
        for s in ('REFUSED_CONTROL_RECEIPT_BYTES','REFUSED_CONTROL_STOP','REFUSED_CONTROL_MANIFEST_OR_P2_ORIGIN','private if known else diagnostic','deadline=600'):
            self.assertIn(s,source)

if __name__=='__main__':unittest.main()
