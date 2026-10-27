import ast
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0,str(Path(__file__).parents[1]))
spec=importlib.util.spec_from_file_location("risk_prefix",Path(__file__).parents[1]/"baseline_prefix.py")
prefix=importlib.util.module_from_spec(spec);spec.loader.exec_module(prefix)


class BaselinePrefixGuards(unittest.TestCase):
    def test_only_exact_bounded_fresh_baseline_request(self):
        request=dict(schema="research.capital-risk-baseline-prefix-request/1",request_id="baseline-prefix-001",
                     stage="baseline-prefix",arm="B",protocol_sha256=prefix.PROTOCOL,transitions=32)
        prefix.validate_request(request)
        for change in [dict(transitions=0),dict(transitions=33),dict(arm="C"),dict(stage="full"),dict(extra=True)]:
            with self.subTest(change=change),self.assertRaises(ValueError):
                prefix.validate_request({**request,**change})

    def test_worker_is_fresh_offline_and_bounded_without_secret_forwarding(self):
        with mock.patch.object(prefix.os,'getuid',return_value=1001,create=True), \
                mock.patch.object(prefix.os,'getgid',return_value=1001,create=True):
            args=prefix.launch_arguments('capital-risk-b-prefix-123-1',Path('/frozen'),Path('/private'),Path('/driver'))
        for flag,value in [('--pull','never'),('--network','none'),('--memory','2g'),('--memory-swap','2g'),('--cpus','1'),
                           ('--pids-limit','64'),('--max-transitions','32'),('--policy',prefix.POLICY)]:
            self.assertEqual(args[args.index(flag)+1],value)
        self.assertIn('--read-only',args)
        self.assertNotIn('--resume',args)
        self.assertNotIn('--checkpoint',args)
        self.assertNotIn('--privileged',args)
        self.assertNotIn(prefix.SECRET,' '.join(args))
        for value in prefix.FORBIDDEN_CREDENTIALS: self.assertNotIn(value,' '.join(args))
        with self.assertRaises(ValueError):
            prefix.launch_arguments('sentinel-paper',Path('/frozen'),Path('/private'),Path('/driver'))

    def test_exact_record_comparator_refuses_changed_or_extra_records(self):
        # Test the pure comparator without importing or instantiating the Core.
        path=Path(__file__).parents[1]/'verify_prefix.py'
        source=ast.parse(path.read_text())
        functions=[node for node in source.body if isinstance(node,ast.FunctionDef) and node.name in {'require','compare_prefix'}]
        space=dict(Path=Path,json=json,hashlib=__import__('hashlib'))
        exec(compile(ast.Module(body=functions,type_ignores=[]),str(path),'exec'),space)
        with tempfile.TemporaryDirectory(prefix='.capital-risk-test-',dir=Path.cwd()) as folder:
            a,b=Path(folder)/'a',Path(folder)/'b'
            raw=b'{"phase":"FORMATION","session":"synthetic"}\n'
            a.write_bytes(raw);b.write_bytes(raw)
            space['compare_prefix'](a,b,1)
            for value in [raw+raw,raw.replace(b'synthetic',b'changed'),b'']:
                a.write_bytes(value)
                with self.assertRaises(ValueError): space['compare_prefix'](a,b,1)

    def test_daily_comparison_requires_explicit_measured_phase(self):
        path=Path(__file__).parents[1]/'verify_prefix.py';tree=ast.parse(path.read_text())
        nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in {'require','compare_prefix'}]
        scope=dict(Path=Path,json=json,hashlib=__import__('hashlib'))
        exec(compile(ast.Module(body=nodes,type_ignores=[]),str(path),'exec'),scope)
        with tempfile.TemporaryDirectory(prefix='.capital-risk-test-',dir=Path.cwd()) as folder:
            a,b=Path(folder)/'a',Path(folder)/'b'
            raw=b'{"phase":"MEASURED","session":"synthetic"}\n';a.write_bytes(raw);b.write_bytes(raw)
            scope['compare_prefix'](a,b,1,phase='MEASURED')
            with self.assertRaises(ValueError):scope['compare_prefix'](a,b,1)

    def test_unknown_writer_is_not_snapshotted_or_treated_as_stopped(self):
        identity='a'*64
        with tempfile.TemporaryDirectory(prefix='.capital-risk-test-',dir=Path.cwd()) as folder:
            output=Path(folder)
            with mock.patch.object(prefix.subprocess,'run',side_effect=[
                    mock.Mock(stdout=identity.encode()),
                    prefix.subprocess.TimeoutExpired('docker wait',1800)]), \
                    mock.patch.object(prefix,'fenced_inspect',return_value={'Id':identity}), \
                    mock.patch.object(prefix,'identity_inspect',side_effect=OSError('synthetic unknown')):
                with self.assertRaises(prefix.UnprovenStopped):
                    prefix.run_worker(['docker','run'],'capital-risk-b-prefix-123-1',output)
            self.assertEqual(list(output.iterdir()),[])

    def test_deadline_stops_only_its_exact_private_worker(self):
        identity='a'*64
        def called(args,**kwargs):
            if args[:2]==['docker','run']: return mock.Mock(stdout=identity.encode())
            if args[:2]==['docker','wait']: raise prefix.subprocess.TimeoutExpired(args,1800)
            return mock.Mock(returncode=0)
        with tempfile.TemporaryDirectory(prefix='.capital-risk-test-',dir=Path.cwd()) as folder:
            with mock.patch.object(prefix.subprocess,'run',side_effect=called) as invoked, \
                    mock.patch.object(prefix,'fenced_inspect',return_value={'Id':identity}), \
                    mock.patch.object(prefix,'identity_inspect',side_effect=[
                        {'State':{'Running':True}}, {'State':{'Running':False}}]):
                with self.assertRaisesRegex(ValueError,'REFUSED_PREFIX_DEADLINE'):
                    prefix.run_worker(['docker','run'],'capital-risk-b-prefix-123-1',Path(folder))
            stops=[call.args[0] for call in invoked.call_args_list if call.args[0][:2]==['docker','stop']]
            self.assertEqual(stops,[['docker','stop','--time','120',identity]])

    def test_ambiguous_launch_does_not_permit_a_financial_snapshot(self):
        with tempfile.TemporaryDirectory(prefix='.capital-risk-test-',dir=Path.cwd()) as folder:
            with mock.patch.object(prefix.subprocess,'run',side_effect=OSError('synthetic launch uncertainty')):
                with self.assertRaises(prefix.UnprovenStopped):
                    prefix.run_worker(['docker','run'],'capital-risk-b-prefix-123-1',Path(folder))
            self.assertEqual(list(Path(folder).iterdir()),[])


if __name__=='__main__': unittest.main()
