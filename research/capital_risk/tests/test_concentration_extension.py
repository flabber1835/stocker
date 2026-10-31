"""Exact own-prefix continuation guards; no local canonical/financial execution."""
from copy import deepcopy
import gzip
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).parents[1];sys.path.insert(0,str(ROOT))
import concentration_extension_job as job
from concentration_predecessor import validate_book,copy_for_resume,preserved_prefixes,digest

class ConcentrationExtensionGuards(unittest.TestCase):
    def book(self,root,policy='B'):
        root.mkdir();raw=b'{"session":"2024-09-19"}\n';journals={}
        for name in ('formation','daily','monthly','watch'):
            data=raw if name=='formation' else b'';(root/(name+'.jsonl')).write_bytes(data)
            journals[name]=dict(bytes=len(data),prefix_sha256=hashlib.sha256(data).hexdigest(),last_record_sha256=hashlib.sha256(data).hexdigest() if data else None)
        base=dict(policy=policy);state=dict(marker='own-'+policy);input_sha=digest(dict(base=base,repairs=[]))
        inner=dict(policy=policy,state=state,state_sha256=digest(state),input_sha256=input_sha)
        inner['checkpoint_sha256']=digest(inner)
        cp=dict(base=base,run=inner,source_cursor='2024-09-19',completed=0,repairs=[],journals=journals);cp['sha256']=digest(cp)
        file=root/'checkpoint.json.gz'
        with gzip.open(file,'wt') as stream:json.dump(cp,stream)
        spec=dict(policy=policy,checkpoint_file_sha256=hashlib.sha256(file.read_bytes()).hexdigest(),outer_sha256=cp['sha256'],
            inner_sha256=inner['checkpoint_sha256'],state_sha256=inner['state_sha256'],input_sha256=input_sha,
            cursor=cp['source_cursor'],formation_closes=1,measured_closes=0,journals=journals)
        return cp,spec

    def test_each_own_checkpoint_roundtrips_without_state_conversion(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            root=Path(tmp);cp,spec=self.book(root/'prior');before=(root/'prior/checkpoint.json.gz').read_bytes()
            self.assertEqual(validate_book(root/'prior',spec,'B'),cp)
            result=copy_for_resume(root/'prior',root/'next',spec,'B')
            self.assertTrue(result['financial_state_unchanged'])
            self.assertEqual((root/'prior/checkpoint.json.gz').read_bytes(),before)
            self.assertEqual((root/'next/predecessor-checkpoints'/(cp['sha256']+'.json.gz')).read_bytes(),before)
            with self.assertRaisesRegex(ValueError,'POLICY_CURSOR'):validate_book(root/'prior',spec,'C')
            wrong=deepcopy(spec);wrong['outer_sha256']='0'*64
            with self.assertRaisesRegex(ValueError,'OUTER'):validate_book(root/'prior',wrong,'B')

    def test_old_prefix_survives_append_and_mutation_refuses(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            root=Path(tmp);_,spec=self.book(root/'prior');copy_for_resume(root/'prior',root/'next',spec,'B')
            path=root/'next/formation.jsonl';old=path.read_bytes();path.write_bytes(old+b'{"session":"2024-09-20"}\n')
            self.assertTrue(preserved_prefixes(root/'next',spec)['all_four_old_prefixes_preserved'])
            path.write_bytes(b'X'+path.read_bytes()[1:])
            with self.assertRaisesRegex(ValueError,'PRESERVED_OLD_PREFIX'):preserved_prefixes(root/'next',spec)

    def test_no_fresh_origin_or_other_arm_is_in_suffix_arguments(self):
        for arm,count in (('B',55),('B0',50),('C',65)):
            tail=job.suffix_tail(arm,dict(formation_closes=count,measured_closes=0))
            self.assertIn('--resume',tail);self.assertEqual(tail[tail.index('--checkpoint')+1],'/out/run-001/checkpoint.json.gz')
            self.assertEqual(tail[tail.index('--max-transitions')+1],str(186-count))
            self.assertEqual(tail[tail.index('--policy')+1],job.POLICIES[arm])
        with self.assertRaises(ValueError):job.suffix_tail('B',dict(formation_closes=186,measured_closes=0))

    def test_execution_and_source_request_are_exact(self):
        request=job.expected_request();execution,spec=job.validate_request(request)
        self.assertFalse(execution['fresh_origin']);self.assertEqual(execution['worker_wait_seconds'],3600)
        self.assertEqual(spec['run_id'],40613063158)
        for change in ({'owner_scope':'old approval'},{'predecessor_sha256':'0'*64},{'extra':True}):
            with self.assertRaises(ValueError):job.validate_request({**request,**change})

    def test_workflow_retrieves_only_approved_predecessor_and_keeps_secret_outer(self):
        text=(ROOT.parents[1]/'.github/workflows/capital-concentration-quarter-extension.yml').read_text()
        self.assertIn('timeout-minutes: 90',text);self.assertIn('retention-days: 7',text)
        self.assertIn('gh run download 40613063158',text);self.assertIn('            .github/workflows\n',text)
        self.assertIn('concentration-extension-*.tar.crseal',text);self.assertNotIn('contents: write',text)
        self.assertNotIn('workflow_dispatch:',text)
        reviewer=(ROOT/'concentration_review.py').read_text();self.assertIn("(root/'predecessor-checkpoints').rglob",reviewer)

if __name__=='__main__':unittest.main()
