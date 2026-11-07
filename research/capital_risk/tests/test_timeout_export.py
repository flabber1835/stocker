"""Timeout/error receipt regression; Docker is fully mocked in local tests."""
import ast
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).parents[1];sys.path.insert(0,str(ROOT))
import baseline_prefix as b
from timeout_export_job import validate_request,proof_command


class TimeoutReceiptGuards(unittest.TestCase):
    def test_hosted_proof_has_no_financial_mode_and_fixed_short_deadline(self):
        r=json.loads((ROOT/'timeout-export-request.json').read_bytes());validate_request(r)
        for change in (dict(financial_sessions=1),dict(deadline_seconds=60),dict(stage='replay')):
            with self.assertRaises(ValueError):validate_request({**r,**change})
        name='capital-risk-timeout-proof-123-1'
        self.assertEqual((b.worker_stage(name),b.worker_arm(name)),('core-integration','CORE_GATE'))
        with patch('os.getuid',return_value=1001,create=True),patch('os.getgid',return_value=1001,create=True):
            args=proof_command(name,Path('/frozen-host'),Path('/private-host'),ROOT)
        self.assertIn('/driver/timeout_marker.py',args)
        self.assertNotIn('--policy',args);self.assertNotIn('--resume',args)
        self.assertEqual(args[args.index('--network')+1],'none')

    def exercise(self,root,*,unknown=False,log_failure=False):
        identity='a'*64;name='capital-risk-core-gate-123-1-basis'
        running=dict(Id=identity,State=dict(Running=True,ExitCode=0,OOMKilled=False))
        stopped=deepcopy(running);stopped['State'].update(Running=False,ExitCode=143)
        def call(args,**kwargs):
            if args[:2]==['docker','run']:return subprocess.CompletedProcess(args,0,stdout=(identity+'\n').encode())
            if args[:2]==['docker','wait']:raise subprocess.TimeoutExpired(args,1)
            if args[:2]==['docker','stop']:return subprocess.CompletedProcess(args,0,stdout=b'')
            if args[:2]==['docker','logs']:
                if log_failure:raise subprocess.TimeoutExpired(args,20)
                kwargs['stdout'].write(b'private synthetic worker log\n')
                return subprocess.CompletedProcess(args,0)
            raise AssertionError('Unexpected Docker operation')
        with patch.object(b.subprocess,'run',side_effect=call),patch.object(b,'fenced_inspect',side_effect=[running,stopped]),patch.object(b,'identity_inspect',side_effect=RuntimeError('unproven') if unknown else [running,stopped]):
            with self.assertRaises(b.UnprovenStopped if unknown else ValueError) as caught:
                b.run_worker(['docker','run','synthetic-image'],name,root,deadline=1)
        return name,caught.exception

    def test_deadline_retains_stop_receipt_before_error_is_propagated(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            root=Path(tmp);self.assertTrue(root.resolve().is_relative_to(ROOT.resolve()))
            name,error=self.exercise(root)
            self.assertEqual(str(error),'REFUSED_PREFIX_DEADLINE')
            receipt=json.loads((root/(name+'-inspect.json')).read_bytes())
            self.assertEqual(receipt['Id'],'a'*64);self.assertFalse(receipt['State']['Running'])
            self.assertEqual((root/(name+'.log')).read_bytes(),b'private synthetic worker log\n')

    def test_unknown_stop_never_saves_a_false_receipt_or_reads_logs(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            root=Path(tmp);name,error=self.exercise(root,unknown=True)
            self.assertIsInstance(error,b.UnprovenStopped)
            self.assertFalse((root/(name+'-inspect.json')).exists())
            self.assertFalse((root/(name+'.log')).exists())

    def test_log_failure_preserves_actual_stop_evidence_and_original_deadline(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            root=Path(tmp);name,error=self.exercise(root,log_failure=True)
            self.assertEqual(str(error),'REFUSED_PREFIX_DEADLINE')
            self.assertTrue((root/(name+'-inspect.json')).exists())
            self.assertEqual(json.loads((root/(name+'-log-capture-error.json')).read_bytes()),dict(type='TimeoutExpired'))

    def test_original_broken_timeout_function_is_rejected_by_regression(self):
        original=b.run_worker
        try:
            raw=(ROOT/'fixtures/pre_timeout_fix_run_worker.py.txt').read_bytes()
            tree=ast.parse(raw);self.assertEqual(len(tree.body),1)
            self.assertEqual(tree.body[0].name,'run_worker')
            exec(compile(tree,'<actual-prior-broken-timeout-function>','exec'),b.__dict__)
            result=unittest.TestResult()
            TimeoutReceiptGuards('test_deadline_retains_stop_receipt_before_error_is_propagated').run(result)
            self.assertFalse(result.wasSuccessful())
        finally:b.run_worker=original


if __name__=='__main__':unittest.main()
