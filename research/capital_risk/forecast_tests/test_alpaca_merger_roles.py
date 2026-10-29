"""Pure recipient-role metadata tests; no financial settlement or Core replay."""
from copy import deepcopy
import hashlib
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parents[3]/'shared'))
import alpaca_fit_merger_roles as roles
from alpaca_fit_identity_repair import digest


class MergerRoleTests(unittest.TestCase):
    def fixture(self):
        record={'id':'synthetic','acquirer_symbol':'BUYER','acquiree_symbol':'TARGET',
            'acquirer_cusip':'111111111','acquiree_cusip':'222222222','acquirer_rate':.25,'acquiree_rate':1,
            'effective_date':'2024-11-01','process_date':'2024-11-01','payable_date':'2024-11-01'}
        reset=('2024-11-01','synthetic','stock_mergers');p={'file':'p.gz','raw_sha256':'1'*64,'sha256':'2'*64}
        data=SimpleNamespace(actions={'synthetic':('stock_mergers',record)},action_proofs={'synthetic':[p]},
            by_ticker={'BUYER':'B','TARGET':'T'},resets={'BUYER':[reset],'TARGET':[reset]})
        entry={'record_sha256':digest(record),'effective_session':'2024-11-01',
            'permanent_id_sha256':hashlib.sha256(b'B').hexdigest(),'response_file':'p.gz',
            'raw_response_sha256':'1'*64,'compressed_response_sha256':'2'*64}
        spec={'schema':'research.alpaca-recipient-role-registry/1','kind':'STOCK_MERGER_ACQUIRER_ONLY',
            'source_manifest_sha256':'0'*64,'events':[entry],'records_sha256':digest([entry['record_sha256']]),
            'predecessor':{'checkpoint':{'session':'2024-10-31'}}}
        return data,spec

    def test_only_buyer_reset_changes_and_source_terms_remain_identical(self):
        data,spec=self.fixture();before=deepcopy(data.actions);target=deepcopy(data.resets['TARGET'])
        result=roles.apply(data,spec,source_manifest_sha256='0'*64)
        self.assertEqual(data.resets['BUYER'],[]);self.assertEqual(data.resets['TARGET'],target)
        self.assertEqual(data.actions,before);self.assertFalse(result['provider_rows_or_financial_state_modified'])

    def test_missing_target_guard_refuses_and_guard_removal_is_detected(self):
        data,spec=self.fixture();data.resets['TARGET']=[]
        with self.assertRaisesRegex(ValueError,'ROLE_ACQUIREE_RESET_REQUIRED'):
            roles.apply(data,spec,source_manifest_sha256='0'*64)
        original=roles.need
        with patch.object(roles,'need',side_effect=lambda v,r:None if r=='ROLE_ACQUIREE_RESET_REQUIRED' else original(v,r)):
            self.assertTrue(roles.apply(data,spec,source_manifest_sha256='0'*64)['events'][0]['acquiree_reset_unchanged'])

    def test_conflicting_buyer_action_is_not_hidden(self):
        data,spec=self.fixture();data.actions['split']=('reverse_splits',{'symbol':'BUYER','ex_date':'2024-11-01'})
        with self.assertRaisesRegex(ValueError,'ROLE_CONFLICTING_ACQUIRER_ACTION'):
            roles.apply(data,spec,source_manifest_sha256='0'*64)

    def test_unbound_or_foreign_buyer_refuses(self):
        data,spec=self.fixture();spec['events'][0]['permanent_id_sha256']='f'*64
        with self.assertRaisesRegex(ValueError,'ROLE_ACQUIRER_ID'):
            roles.apply(data,spec,source_manifest_sha256='0'*64)


if __name__=='__main__':unittest.main()
