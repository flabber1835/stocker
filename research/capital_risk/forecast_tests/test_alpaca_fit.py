import itertools
import json
from pathlib import Path
import sys
import unittest
import types
from unittest.mock import patch
from copy import deepcopy

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import alpaca_fit_collect as capture
import alpaca_fit_policy as fitting


class ProviderCaptureTests(unittest.TestCase):
    def test_protocol_finite_class_includes_baseline(self):
        p=json.loads((Path(__file__).resolve().parents[1]/'alpaca-fit-protocol.json').read_bytes())
        settings=list(itertools.product(*p['grid'].values()))
        self.assertEqual(len(settings),108)
        self.assertIn(('0.88',5,8,'0.55'),settings)
        self.assertEqual(p['training_end'],'2025-12-31')
        self.assertEqual(p['validation_start'],'2026-01-02')
        self.assertFalse(p['new_forecaster'])

    def test_mapping_requires_broad_type_identity(self):
        asset={'asset_id':'synthetic-id','ticker':'SYNTHETIC','exchange':'NASDAQ','name':'Synthetic'}
        row={'marketSector':'Equity','exchCode':'US','ticker':'SYNTHETIC',
             'compositeFIGI':'synthetic-A','shareClassFIGI':'synthetic-B',
             'securityType':'Common Stock','securityType2':'Common Stock'}
        mapped,reason=capture.classify(asset,{'data':[row]})
        self.assertIsNone(reason);self.assertEqual(mapped['asset_id'],'synthetic-id')
        self.assertEqual(capture.classify(asset,{'data':[{**row,'securityType2':'Preferred Stock'}]})[1],'NON_ORDINARY_EQUITY')
        self.assertEqual(capture.classify(asset,{'data':[row,{**row,'compositeFIGI':'synthetic-C'}]})[1],'AMBIGUOUS_MAPPING')

    def test_empty_warning_exclusion_is_explicit_error_refuses(self):
        asset={'ticker':'SYNTHETIC'}
        self.assertEqual(capture.classify(asset,{'warning':'No identifier found'}),(None,'NO_MAPPING'))
        with self.assertRaisesRegex(ValueError,'FIGI_PROVIDER_ERROR'):
            capture.classify(asset,{'error':'provider failure'})

    def test_account_endpoint_refuses_before_network_or_secret_access(self):
        client=capture.Client.__new__(capture.Client)
        with self.assertRaisesRegex(ValueError,'ENDPOINT_OR_METHOD'):
            client.call('https://paper-api.alpaca.markets/v2/account')
        with self.assertRaisesRegex(ValueError,'ENDPOINT_OR_METHOD'):
            client.call(capture.ACTIONS,body={'bad':'method'})


class SelectionTests(unittest.TestCase):
    def setup_records(self):
        protocol=json.loads((Path(__file__).resolve().parents[1]/'alpaca-fit-protocol.json').read_bytes())
        profiles,base=fitting.profiles(protocol)
        records=[{'profile_id':p.id,'period':'TRAINING','candidate_validation_metrics_included':False,'status':'REVIEWED',
                  'turnover':'1','additional_funded_transitions':0,'metrics':{'start':'2025-01-02','end':'2025-12-31',
                   'closes':250,'multiple':'11/10','cagr':.1,'maximum_drawdown_magnitude':'1/5'}} for p in profiles]
        return protocol,records,base

    def test_exact_finite_selection_and_full_coverage(self):
        protocol,records,base=self.setup_records();winner=next(r for r in records if r['profile_id']!=base.id)
        winner['metrics'].update(multiple='6/5',cagr=.2,maximum_drawdown_magnitude='1/10');winner['additional_funded_transitions']=1
        result=fitting.select(records,protocol)
        self.assertEqual(result['best_training_joint_gain'],winner['profile_id'])
        self.assertEqual(result['selected'],[winner['profile_id']])
        self.assertEqual(result['global_gap_within_declared_finite_class'],'0')
        self.assertEqual(result['global_gap_over_all_possible_policies'],'UNKNOWN')

    def test_validation_and_short_prefix_refuse(self):
        protocol,records,base=self.setup_records();records[0]['candidate_validation_metrics_included']=True
        with self.assertRaisesRegex(ValueError,'VALIDATION_SELECTION_LEAK'):fitting.select(records,protocol)
        protocol,records,base=self.setup_records();records[0]['metrics']['end']='2025-11-30'
        with self.assertRaisesRegex(ValueError,'TRAINING_AXIS'):fitting.select(records,protocol)

    def test_refused_setting_does_not_become_complete_search(self):
        protocol,records,base=self.setup_records()
        row=next(r for r in records if r['profile_id']!=base.id);row['status']='REFUSED';row.pop('metrics')
        result=fitting.select(records,protocol)
        self.assertFalse(result['finite_class_exhaustive'])
        self.assertEqual(result['global_gap_within_declared_finite_class'],'UNKNOWN')

    def test_private_leaf_execution_is_hosted_only(self):
        protocol,records,base=self.setup_records()
        with self.assertRaisesRegex(ValueError,'LOCAL_CONTROLLER_REPLAY'):
            fitting.leaf(Path('nonexistent-no-read'),base,'0'*64)

    def test_private_input_adapter_cannot_start_local_book(self):
        from alpaca_fit_inputs import Inputs
        with self.assertRaisesRegex(ValueError,'LOCAL_FINANCIAL_INPUT_EXECUTION'):
            Inputs(Path('nonexistent'),Path('nonexistent'),{},'0'*64)

    def test_training_leak_guard_removal_is_detected(self):
        mutant=types.FunctionType(fitting.select.__code__,{**fitting.select.__globals__,'need':lambda value,reason:None})
        result=unittest.TestResult()
        with patch.object(fitting,'select',mutant):
            SelectionTests('test_validation_and_short_prefix_refuse').run(result)
        self.assertFalse(result.wasSuccessful(),'selection test must reject actual guard removal')


if __name__=='__main__':unittest.main()
