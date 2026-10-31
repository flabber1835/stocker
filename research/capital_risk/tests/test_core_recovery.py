"""Pure source-succession guards; no canonical runtime or market replay."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).parents[1];sys.path.insert(0,str(ROOT))
from core_recovery import bind_checkpoint,digest,sha,unchanged_financial_state,successor_base,COUNTER,IDENTITY
from core_recovery_job import validate_request
from baseline_prefix import worker_stage,worker_arm


class RecoveryGuards(unittest.TestCase):
    def test_exact_checkpoint_file_outer_inner_state_and_source_are_required(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            path=Path(tmp)/'cp';path.write_bytes(b'synthetic-compressed-file-identity')
            state=dict(cash=50000);run=dict(state=state,state_sha256=digest(state),input_sha256='3'*64)
            run['checkpoint_sha256']=digest(run)
            saved=dict(run=run,base=dict(sources={COUNTER:'a'*64}),source_cursor='2024-07-02',
                completed=0,stats=None,spy_base=None,repairs=[],retries=dict(transitions=0,last_session=None),
                journals={n:dict(bytes=0) for n in ('formation','daily','monthly','watch')})
            saved['sha256']=digest(saved)
            spec=dict(file_sha256=sha(path),outer_sha256=saved['sha256'],inner_sha256=run['checkpoint_sha256'],
                state_sha256=run['state_sha256'],input_sha256=run['input_sha256'],base_sha256=digest(saved['base']),
                sources_sha256=digest(saved['base']['sources']),source_cursor=saved['source_cursor'])
            bind_checkpoint(saved,spec,path)
            for field in spec:
                with self.subTest(field=field),self.assertRaisesRegex(ValueError,'EXACT_WARMUP'):
                    bind_checkpoint(saved,{**spec,field:'wrong'},path)
            corrupt=deepcopy(saved);corrupt['run']['state']['cash']-=1
            with self.assertRaises(ValueError):bind_checkpoint(corrupt,spec,path)

    def test_source_bridge_permits_only_counter_and_research_identity(self):
        old=dict(sources={COUNTER:'a'*64,'economic.py':'b'*64},capital='50000')
        current={**old['sources'],COUNTER:'c'*64}
        self.assertEqual(successor_base(old,current),{**old,'sources':current})
        with self.assertRaises(ValueError):successor_base(old,{**current,'economic.py':'d'*64})
        before=dict(wealth_core=dict(cash=50000),pending=[],strategy_identity={IDENTITY:'a','controller':'keep'})
        after={**deepcopy(before),'strategy_identity':{IDENTITY:'b','controller':'keep'}}
        unchanged_financial_state(before,after)
        for change in ('cash','pending','controller','no_identity_change'):
            bad=deepcopy(after)
            if change=='cash':bad['wealth_core']['cash']-=1
            if change=='pending':bad['pending']=[dict(quantity=1)]
            if change=='controller':bad['strategy_identity']['controller']='changed'
            if change=='no_identity_change':bad=deepcopy(before)
            with self.subTest(change=change),self.assertRaises(ValueError):unchanged_financial_state(before,bad)

    def test_recovery_names_do_not_admit_arbitrary_worker_phases(self):
        for phase in ('preflight','bridge'):
            name='capital-risk-core-recovery-stress2021-123-1-'+phase
            self.assertEqual((worker_stage(name),worker_arm(name)),('core-integration','CORE_GATE'))
        for suffix in ('run','restart','resume','bridge-extra'):
            with self.assertRaises(ValueError):worker_stage('capital-risk-core-recovery-stress2021-123-1-'+suffix)

    def test_financial_guard_removal_is_detected(self):
        # Run the real mutation test against an intentionally removed guard.
        # A passing inner test would mean the falsifier failed to protect cash.
        with patch(__name__+'.unchanged_financial_state',lambda *args:None):
            result=unittest.TestResult()
            RecoveryGuards('test_source_bridge_permits_only_counter_and_research_identity').run(result)
        self.assertFalse(result.wasSuccessful())

    def test_exact_qualification_request_and_asset_scope(self):
        path=ROOT/'core-recovery-request.json'
        r=json.loads(path.read_bytes());validate_request(r)
        for change in (dict(old_source_commit='0'*40),dict(stage='replay'),dict(compiler_fixture_sha256='0'*64)):
            with self.assertRaises(ValueError):validate_request({**r,**change})
        wrong=deepcopy(r);wrong['windows']['recent2025']['encrypted_outputs'][0]['arm']='PAPER'
        with self.assertRaises(ValueError):validate_request(wrong)


if __name__=='__main__':unittest.main()
