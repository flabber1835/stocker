from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import alpaca_fit_job as job


class HostedWorkerTests(unittest.TestCase):
    def item(self):
        return {'Name':'/capital-alpaca-fit-baseline-123-1','Id':'1'*64,'Image':job.EXECUTION_IMAGE,
            'State':{'Running':False,'ExitCode':143,'OOMKilled':False},
            'HostConfig':{'NetworkMode':'none','Memory':8*1024**3,'MemorySwap':8*1024**3,
                'NanoCpus':2_000_000_000,'PidsLimit':64,'ReadonlyRootfs':True,'CapDrop':['ALL'],
                'SecurityOpt':['no-new-privileges']},
            'Config':{'Labels':{'research.study':'alpaca-owned55-fit-001','research.stage':'canonical-baseline'},
                'WorkingDir':'/src','User':'1001:1001','Env':['ALPACA_FIT_HOSTED=1']},
            'Mounts':[{'Destination':p,'Type':'bind','RW':p=='/out'} for p in ('/src','/inputs','/prefix','/bil','/out')]}

    def check(self,item):
        with patch.object(job.os,'getuid',return_value=1001,create=True),patch.object(job.os,'getgid',return_value=1001,create=True),\
             patch.object(job.subprocess,'run',return_value=subprocess.CompletedProcess([],0,json.dumps([item]).encode())):
            return job.inspect('capital-alpaca-fit-baseline-123-1','1'*64)

    def test_actual_fences_require_offline_readonly_no_secrets(self):
        self.check(self.item())
        for field in ('network','swap','writable','credential','replaced'):
            item=self.item()
            if field=='network':item['HostConfig']['NetworkMode']='bridge'
            elif field=='swap':item['HostConfig']['MemorySwap']=-1
            elif field=='writable':item['Mounts'][0]['RW']=True
            elif field=='credential':item['Config']['Env'].append('ALPACA_API_KEY=synthetic-not-a-secret')
            else:item['Id']='2'*64
            with self.subTest(field=field),self.assertRaises(ValueError):self.check(item)

    def test_timeout_receipt_exists_before_logs_and_export(self):
        with tempfile.TemporaryDirectory() as f:
            root=Path(f);calls=[]
            def run(argv,**kwargs):
                calls.append(argv[1])
                if argv[1]=='run':return subprocess.CompletedProcess(argv,0,('1'*64).encode())
                if argv[1]=='wait':raise subprocess.TimeoutExpired(argv,3)
                if argv[1]=='logs':self.assertTrue((root/'worker-inspect.json').is_file())
                return subprocess.CompletedProcess(argv,0,b'')
            with patch.object(job,'inspect',return_value=self.item()),patch.object(job.subprocess,'run',side_effect=run):
                result=job.stopped_run(['docker','run'],'capital-alpaca-fit-baseline-123-1',root,3)
            self.assertTrue(result['stopped']);self.assertEqual(result['wait_error'],'TimeoutExpired')
            self.assertEqual(result['exit_code'],143);self.assertEqual(calls,['run','wait','logs'])

    def test_unknown_stop_never_becomes_export_authority(self):
        with tempfile.TemporaryDirectory() as f:
            with (patch.object(job,'inspect',side_effect=ValueError('synthetic unknown')),
                  patch.object(job.subprocess,'run',return_value=subprocess.CompletedProcess([],0,('1'*64).encode()))):
                with self.assertRaises(job.StopUnknown):
                    job.stopped_run(['docker','run'],'capital-alpaca-fit-baseline-123-1',Path(f),3)
            self.assertFalse((Path(f)/'worker-inspect.json').exists())

    def test_worker_fence_guard_removal_is_detected(self):
        namespace={**job.inspect_kind.__globals__,'need':lambda value,reason:None}
        mutant=types.FunctionType(job.inspect_kind.__code__,namespace)
        result=unittest.TestResult()
        with patch.object(job,'inspect_kind',mutant):
            HostedWorkerTests('test_actual_fences_require_offline_readonly_no_secrets').run(result)
        self.assertFalse(result.wasSuccessful(),'fence suite must reject actual guard removal')


if __name__=='__main__':unittest.main()
