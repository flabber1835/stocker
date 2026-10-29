"""Changed factual metadata boundary only; no Core/account replay."""
from copy import deepcopy
import hashlib
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parents[3]/'shared'))
import alpaca_fit_identity_repair as repair


class SparseNameFactTests(unittest.TestCase):
    def fixture(self,**changes):
        record={'id':'synthetic-event','old_symbol':'OLD','new_symbol':'NEW','old_cusip':'111111111',
            'new_cusip':'111111111','process_date':'2024-08-05',**changes}
        proof={'file':'synthetic.gz','raw_sha256':'1'*64,'sha256':'2'*64}
        data=SimpleNamespace(actions={'synthetic-event':('name_changes',record)},by_ticker={'NEW':'synthetic-sid'},
            action_proofs={'synthetic-event':[proof]},resets={'NEW':[('2024-08-05','synthetic-event','name_changes'),
                ('2023-04-03','other-event','mergers')]},price_witness=b'unchanged')
        descriptor={'schema':'research.alpaca-sparse-factual-identity/1','kind':'SAME_CUSIP_NAME_ONLY',
            'record_kind':'name_changes','source_manifest_sha256':'0'*64,'record_sha256':repair.digest(record),
            'effective_session':'2024-08-05','permanent_id_sha256':hashlib.sha256(b'synthetic-sid').hexdigest(),
            'response_file':proof['file'],'raw_response_sha256':proof['raw_sha256'],
            'compressed_response_sha256':proof['sha256'],'primary_extraction_sha256':'3'*64}
        return data,descriptor

    def test_exact_name_fact_removes_only_its_reset(self):
        data,spec=self.fixture();before=deepcopy(data.actions)
        proof=repair.apply(data,spec,source_manifest_sha256='0'*64)
        self.assertEqual(data.resets,{'NEW':[('2023-04-03','other-event','mergers')]})
        self.assertEqual(data.actions,before);self.assertEqual(data.price_witness,b'unchanged')
        self.assertFalse(proof['provider_rows_or_financial_state_modified'])

    def test_unbound_action_record_refuses(self):
        data,spec=self.fixture();spec['record_sha256']='f'*64
        with self.assertRaisesRegex(ValueError,'EXACT_NAME_RECORD_NOT_UNIQUE'):
            repair.apply(data,spec,source_manifest_sha256='0'*64)

    def test_different_cusip_refuses_and_guard_removal_is_detected(self):
        data,spec=self.fixture(new_cusip='222222222')
        with self.assertRaisesRegex(ValueError,'NAME_ONLY_CUSIP_SYMBOL_DATE'):
            repair.apply(data,spec,source_manifest_sha256='0'*64)
        original=repair.need
        with patch.object(repair,'need',side_effect=lambda v,r:None if r=='NAME_ONLY_CUSIP_SYMBOL_DATE' else original(v,r)):
            result=repair.apply(data,spec,source_manifest_sha256='0'*64)
        self.assertEqual(result['record_sha256'],spec['record_sha256'])

    def test_another_structural_event_at_boundary_refuses(self):
        data,spec=self.fixture();data.actions['split']=('forward_splits',{'symbol':'NEW','ex_date':'2024-08-05'})
        with self.assertRaisesRegex(ValueError,'CONFLICTING_NAME_ACTION'):
            repair.apply(data,spec,source_manifest_sha256='0'*64)

    def test_listing_collision_and_foreign_permanent_id_refuse(self):
        data,spec=self.fixture();data.by_ticker['OLD']='another-sid'
        with self.assertRaisesRegex(ValueError,'UNIQUE_NAME_TARGET_LISTING'):
            repair.apply(data,spec,source_manifest_sha256='0'*64)
        data,spec=self.fixture();spec['permanent_id_sha256']='f'*64
        with self.assertRaisesRegex(ValueError,'NAME_PERMANENT_ID'):
            repair.apply(data,spec,source_manifest_sha256='0'*64)


if __name__=='__main__':unittest.main()
