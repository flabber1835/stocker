import json,hashlib,sys,unittest
from pathlib import Path
from unittest.mock import Mock,MagicMock
ROOT=Path(__file__).parents[1];sys.path.insert(0,str(ROOT))
from weighted_job import inspect_weighted
from weighted_resume import resume_prefix
from weighted_screen import Screen,digest,encoded
from runtime_identity import EXECUTION_IMAGE

class SuffixGuards(unittest.TestCase):
    def inspection(self):
        name='capital-risk-br-suffix-123-1'
        v=dict(Name='/'+name,Id='a'*64,Image=EXECUTION_IMAGE,
            State=dict(Running=False,Status='exited',ExitCode=0,OOMKilled=False),
            Config=dict(Labels={'research.experiment':'capital-risk-20261027','research.stage':'weighted-suffix','research.arm':'BR'},
                        WorkingDir='/fixed',User='1001:1001',Env=[]),
            HostConfig=dict(NetworkMode='none',ReadonlyRootfs=True,Memory=2*1024**3,MemorySwap=2*1024**3,
                NanoCpus=1000000000,PidsLimit=64,CapDrop=['ALL'],SecurityOpt=['no-new-privileges']),
            Mounts=[dict(Type='bind',Destination=d,RW=d=='/out') for d in ('/frozen','/out','/driver','/resume')])
        p=Mock();p.is_file.return_value=True;p.read_bytes.side_effect=lambda:json.dumps(v).encode()
        return name,v,p

    def test_readonly_four_mount_suffix_and_actual_stop(self):
        name,v,p=self.inspection();self.assertTrue(inspect_weighted(p,name)['stopped'])
        v['Mounts'][-1]['RW']=True
        with self.assertRaises(ValueError):inspect_weighted(p,name)
        v['Mounts'][-1]['RW']=False;v['State']['Running']=True
        with self.assertRaises(ValueError):inspect_weighted(p,name)

    def test_missing_resume_or_source_fence_refuses(self):
        name,v,p=self.inspection();v['Mounts'].pop()
        with self.assertRaises(ValueError):inspect_weighted(p,name)
        name,v,p=self.inspection();v['Image']='wrong'
        with self.assertRaises(ValueError):inspect_weighted(p,name)

    def prefix(self):
        rows=[];samples=[];chain='0'*64
        for day in ('2020-01-02','2020-01-03','2020-01-06'):
            rows.append(dict(phase='MEASURED',session=day,state_sha256='a'*64,input_sha256='b'*64,chain_sha256='c'*64,
                economics=dict(last_session=day,strategy_nav='50000')))
        for row in rows[:2]:
            record=dict(session=row['session'],B_economics=row['economics'],R_economics=row['economics'],
                risk=dict(reduced=False,recovery=0,last_session=row['session']),baseline_state_sha256='a'*64,
                baseline_input_sha256='b'*64,baseline_chain_sha256='c'*64)
            chain=digest(dict(previous=chain,record=record));samples.append({**record,'screen_chain_sha256':chain})
        raw=b''.join(encoded(r)+b'\n' for r in samples);prior=MagicMock();prior.__truediv__.return_value.read_bytes.return_value=raw
        d=dict(contract_sha256='d'*64,prefix_bytes=len(raw),prefix_sha256=hashlib.sha256(raw).hexdigest(),
            committed_records=2,last_session='2020-01-03',next_session='2020-01-06')
        return prior,rows,d,raw

    def test_exact_actual_account_state_is_only_copied(self):
        prior,rows,d,raw=self.prefix();engine,samples,prefix,saved=resume_prefix(prior,'d'*64,rows,d,Screen)
        self.assertEqual(prefix,raw);self.assertEqual(engine.completed,2);self.assertEqual(engine.checkpoint(),saved)
        self.assertEqual(saved['accounts']['R'],samples[-1]['R_economics'])

    def test_wrong_prefix_contract_or_next_session_refuses(self):
        prior,rows,d,raw=self.prefix()
        for change in (dict(prefix_sha256='0'*64),dict(contract_sha256='e'*64),dict(next_session='2020-01-07')):
            with self.assertRaises(ValueError):resume_prefix(prior,'d'*64,rows,{**d,**change},Screen)

if __name__=='__main__':unittest.main()
