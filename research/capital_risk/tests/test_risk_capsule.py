"""Lossless transport falsifiers on literal hash fixtures, no financial model."""
from pathlib import Path
from copy import deepcopy
import ast,gzip,json,hashlib,sys,tempfile,unittest
ROOT=Path(__file__).parents[1];sys.path.insert(0,str(ROOT))
from risk_capsule import encode,digest,compact_event,expand_event,compact_checkpoint,expand_checkpoint,pack_book,verify_book

class CapsuleTests(unittest.TestCase):
    def fixture(self):
        state=dict(applied_events=['synthetic-marker'],cash='100',fixed='literal-hash-fixture')
        event=dict(record=dict(event=dict(event_id='synthetic-marker',operation='SYNTHETIC_HASH_MARKER'),state_without_chain=state),context={})
        return state,event
    def test_event_roundtrip_and_history_and_balance_falsifiers(self):
        _,event=self.fixture();compact,history=compact_event(event,[]);self.assertEqual(expand_event(compact,[]),(event,history))
        bad=deepcopy(compact);bad['history_records']=0
        with self.assertRaises(ValueError):expand_event(bad,[])
        bad=deepcopy(compact);bad['observation']['record']['state_without_chain']['cash']='101'
        with self.assertRaises(ValueError):expand_event(bad,[])
        bad=deepcopy(compact);bad['observation']['record']['event']['event_id']='other-marker'
        with self.assertRaises(ValueError):expand_event(bad,[])
    def test_checkpoint_roundtrip_and_mutation(self):
        state,event=self.fixture();cp=dict(runtime=dict(account=dict(state=state,state_sha256=digest(state)),event_count=1),journals={})
        compact=compact_checkpoint(cp,['synthetic-marker'],'checkpoint.json.gz','a'*64);self.assertEqual(expand_checkpoint(compact,['synthetic-marker']),cp)
        bad=deepcopy(compact);bad['checkpoint']['runtime']['account']['state']['cash']='0'
        with self.assertRaises(ValueError):expand_checkpoint(bad,['synthetic-marker'])
    def test_full_transport_prefixes_and_missing_checkpoint_refusal(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            source=Path(tmp)/'source';source.mkdir();state,event=self.fixture();raw=encode(event)+b'\n';empty=dict(bytes=0,records=0,prefix_sha256=hashlib.sha256(b'').hexdigest())
            for name,value in [('events',raw),('daily',b''),('formation',b'')]:
                with gzip.open(source/(name+'.jsonl.gz'),'wb') as f:f.write(value)
            journals=dict(events=dict(bytes=len(raw),records=1,prefix_sha256=hashlib.sha256(raw).hexdigest()),daily=empty,formation=empty)
            cp=dict(runtime=dict(account=dict(state=state,state_sha256=digest(state)),event_count=1),journals=journals)
            with gzip.open(source/'checkpoint.json.gz','wb') as f:f.write(encode(cp)+b'\n')
            dest=Path(tmp)/'capsule';pack_book(source,dest);proof,restored=verify_book(dest);self.assertEqual(cp,restored);self.assertEqual(proof['journals']['events']['records'],1)
            with gzip.open(dest/'checkpoints.compact.jsonl.gz','wb') as f:f.write(b'')
            with self.assertRaises(ValueError):verify_book(dest)

    def test_raw_byte_commitment_guard_removal_falsifier(self):
        import risk_capsule as module
        _,event=self.fixture();compact,_=compact_event(event,[]);compact['observation']['record']['state_without_chain']['cash']='101'
        with self.assertRaisesRegex(ValueError,'ORIGINAL_EVENT_BYTES'):expand_event(compact,[])
        node=next(n for n in ast.parse((ROOT/'risk_capsule.py').read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='expand_event')
        class Remove(ast.NodeTransformer):
            def visit_Expr(self,n):
                if isinstance(n.value,ast.Call) and n.value.args and isinstance(n.value.args[-1],ast.Constant) and n.value.args[-1].value=='CAPSULE_ORIGINAL_EVENT_BYTES':return None
                return n
        tree=Remove().visit(ast.Module(body=[node],type_ignores=[]));ast.fix_missing_locations(tree);scope=dict(module.__dict__);exec(compile(tree,'removed-capsule-raw-byte-guard','exec'),scope)
        mutated,_=scope['expand_event'](compact,[]);self.assertEqual(mutated['record']['state_without_chain']['cash'],'101')

    def test_selected_validation_has_only_own_suffix_and_locked_selection(self):
        worker=(ROOT/'risk_validation_worker.py').read_text();outer=(ROOT/'risk_validation_job.py').read_text()
        for text in ('REFUSED_LOCAL_SELECTED_VALIDATION','checkpoint=boundary[','boundary=boundary',"result['final']==final",'finance_path_sha256'):self.assertIn(text,worker)
        for text in ('REFUSED_COMMITTED_SELECTION_BYTES','REFUSED_CHANGED_SELECTED_FINANCIAL_SOURCE_','REFUSED_SELECTED_NATIVE_STOPS','main_paths_replayed=False','len(selection[\'ranking\'])==12'):self.assertIn(text,outer)
        self.assertNotIn('holding_account import Runtime',outer)
        workflow=(ROOT.parents[1]/'.github/workflows/capital-bounded-risk-validation.yml').read_text()
        for text in ('timeout-minutes: 45','retention-days: 7','contents: read','github.run_attempt == 1','fetch-depth: 2'):self.assertIn(text,workflow)
        for text in ('workflow_dispatch:','contents: write','daily.jsonl.gz'):self.assertNotIn(text,workflow)

if __name__=='__main__':unittest.main()
