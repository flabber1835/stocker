import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0,str(Path(__file__).parents[1]))
import suffix_contract as contract
import baseline_suffix as suffix


class SuffixGuards(unittest.TestCase):
    def remote(self):
        p=contract.request_template()['predecessor']
        run=dict(id=p['run_id'],run_attempt=1,head_sha=p['source_commit'],path=p['workflow_path'],
            head_branch='codex/capital-risk-research',event='push',status='completed',conclusion='success',
            actor=dict(login='flabber1835'),repository=dict(id=1233957439,full_name='flabber1835/stocker'))
        artifacts=dict(artifacts=[dict(id=p['artifact_id'],name=p['artifact_name'],expired=False,
            digest=p['artifact_digest'],size_in_bytes=p['artifact_bytes'])])
        return run,artifacts

    def test_request_forbids_restart_zero_limit_different_book_and_extra_fields(self):
        good=contract.request_template();contract.validate_request(good)
        for changed in [dict(transitions=0),dict(transitions=32),dict(arm='C'),dict(extra=True),dict(target_session='2026-07-31')]:
            with self.subTest(changed=changed),self.assertRaises(ValueError):
                contract.validate_request({**good,**changed})
        bad=copy.deepcopy(good);bad['predecessor']['attempt']=True
        with self.assertRaises(ValueError):contract.validate_request(bad)

    def test_remote_run_owner_branch_attempt_workflow_and_success_are_bound(self):
        run,artifacts=self.remote();good=contract.request_template()
        contract.verify_remote(run,artifacts,good)
        for change in [dict(actor=dict(login='other')),dict(head_branch='main'),dict(run_attempt=2),
                       dict(head_sha='0'*40),dict(event='pull_request'),dict(conclusion='failure'),
                       dict(path='.github/workflows/sentinel-publish.yml'),dict(repository=dict(id=1,full_name='other/repo'))]:
            with self.subTest(change=change),self.assertRaises(ValueError):
                contract.verify_remote({**run,**change},artifacts,good)

    def test_remote_artifact_id_digest_size_name_and_expiry_are_bound(self):
        run,artifacts=self.remote();good=contract.request_template()
        for change in [dict(id=1),dict(digest='sha256:'+'0'*64),dict(size_in_bytes=1),dict(name='latest'),dict(expired=True)]:
            bad=copy.deepcopy(artifacts);bad['artifacts'][0].update(change)
            with self.subTest(change=change),self.assertRaises(ValueError):contract.verify_remote(run,bad,good)

    def test_suffix_is_exact_resume_and_reviews_have_no_financial_entrypoint(self):
        request=contract.request_template()
        with mock.patch.object(suffix.os,'getuid',return_value=1001,create=True), \
                mock.patch.object(suffix.os,'getgid',return_value=1001,create=True):
            with self.assertRaisesRegex(ValueError,'REFUSED_SUFFIX_WORKER_STAGE'):
                suffix.suffix_arguments('capital-risk-b-prefix-123-1',Path('/frozen'),Path('/private'),Path('/driver'),request)
            args=suffix.suffix_arguments('capital-risk-b-suffix-123-1',Path('/frozen'),Path('/private'),Path('/driver'),request)
            self.assertIn('--resume',args)
            self.assertEqual(args[args.index('--max-transitions')+1],'21')
            self.assertEqual(args[args.index('--checkpoint')+1],'/out/run-001/checkpoint.json.gz')
            self.assertIn('research.stage=baseline-suffix',args)
            for forbidden in ['--source-successor','--capital','--repair-overlay','--privileged']:
                self.assertNotIn(forbidden,args)
            for phase in ['preflight','postflight']:
                review=suffix.suffix_arguments('capital-risk-b-suffix-123-1-'+phase,Path('/frozen'),Path('/private'),Path('/driver'),request,phase=phase)
                self.assertIn('/driver/verify_suffix.py',review)
                self.assertNotIn('--resume',review)
                self.assertNotIn('--max-transitions',review)

    def test_wrong_receipt_is_rejected_before_decryption_or_restore(self):
        request=contract.request_template();p=request['predecessor']
        good=dict(status='PREFIX_PASSED',run_id=str(p['run_id']),source_commit=p['source_commit'],
            protocol_sha256=contract.PROTOCOL,arm='B',full_baseline_gate_satisfied=False,
            encrypted_output=dict(name=p['cipher_name'],bytes=p['cipher_bytes'],sha256=p['cipher_sha256']))
        with tempfile.TemporaryDirectory(prefix='.capital-risk-test-',dir=Path.cwd()) as folder:
            root=Path(folder)
            for change in [dict(status='PREFIX_REFUSED'),dict(source_commit='0'*40),dict(arm='C'),dict(full_baseline_gate_satisfied=True)]:
                (root/'baseline-prefix.json').write_text(json.dumps({**good,**change}))
                with self.subTest(change=change),self.assertRaisesRegex(ValueError,'REFUSED_PREDECESSOR_RECEIPT'):
                    suffix.restore_predecessor(request,root,root/'private',b'x'*32)
                self.assertFalse((root/'private').exists())

    def test_dade_request_keeps_actual_predecessor_and_frozen_fact_terms(self):
        request=contract.request_template('baseline-suffix-002');contract.validate_request(request)
        self.assertEqual(request['transitions'],77)
        self.assertEqual(request['target_measured_closes'],4)
        for changed in [dict(cash_per_share=76),dict(cash_per_share=77.0),dict(case='other'),dict(overlay_sha256='0'*64)]:
            bad=copy.deepcopy(request);bad['repair'].update(changed)
            with self.subTest(changed=changed),self.assertRaises(ValueError):contract.validate_request(bad)
        with mock.patch.object(suffix.os,'getuid',return_value=1001,create=True), \
                mock.patch.object(suffix.os,'getgid',return_value=1001,create=True):
            args=suffix.suffix_arguments('capital-risk-b-suffix-123-1',Path('/frozen'),Path('/private'),Path('/driver'),request)
        self.assertEqual(args[args.index('--max-transitions')+1],'77')
        self.assertEqual(args[args.index('--repair-overlay')+1],'/out/research-repairs/dade/overlay.json')
        self.assertIn('--resume',args)
        self.assertNotIn('--source-successor',args)

    def test_dade_receipt_cannot_be_replaced_by_an_older_prefix_receipt(self):
        request=contract.request_template('baseline-suffix-002');p=request['predecessor']
        receipt=dict(status='PREFIX_PASSED',run_id=str(p['run_id']),source_commit=p['source_commit'],
            protocol_sha256=contract.PROTOCOL,arm='B',full_baseline_gate_satisfied=False,
            encrypted_output=dict(name=p['cipher_name'],bytes=p['cipher_bytes'],sha256=p['cipher_sha256']))
        with tempfile.TemporaryDirectory(prefix='.capital-risk-test-',dir=Path.cwd()) as folder:
            path=Path(folder);(path/'baseline-suffix.json').write_text(json.dumps(receipt))
            with self.assertRaisesRegex(ValueError,'REFUSED_PREDECESSOR_RECEIPT'):
                suffix.restore_predecessor(request,path,path/'private',b'x'*32)

    def test_ancestry_is_immutable_across_generations(self):
        with tempfile.TemporaryDirectory(prefix='.capital-risk-test-',dir=Path.cwd()) as folder:
            path=Path(folder)/'lineage/checkpoints/hash.json.gz'
            suffix.retain_immutable(path,b'original')
            suffix.retain_immutable(path,b'original')
            with self.assertRaisesRegex(ValueError,'REFUSED_ANCESTRY_COLLISION'):
                suffix.retain_immutable(path,b'changed')
            self.assertEqual(path.read_bytes(),b'original')
