"""Hand-valued dollar geometry; no account or historical replay locally."""
from copy import deepcopy
from fractions import Fraction as Q
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from alpaca_fit_account import projection,defensive_factors,Runtime


class AccountGeometryTests(unittest.TestCase):
    def row(self):
        return {'session':'2024-12-31','shadow_nav':1000.,'state_sha256':'1'*64,'input_sha256':'2'*64,
            'wealth_core':{'episodes':{'0':{'security_id':'A','ticker':'A','slot_id':0,'signal_date':'2024-12-02','current_shares':2.}}},
            'prices':{'A':{'raw_close':'50'}},'pending':[{'operation':'OPEN_SLOT_POSITION','security_id':'B','ticker':'B',
                'slot_id':1,'signal_session':'2024-12-31','intended_dollars':50.}]}

    def test_initial_funding_uses_known_prior_close_weights_and_nav20(self):
        result=projection(self.row(),nav=Q(5000),target='.5',held_target='0',execution_session='2025-01-02',initial=True)
        self.assertEqual(Q(result['targets']['2024-12-02/0']['dollars']),250)
        self.assertEqual(Q(result['targets']['2024-12-31/1']['dollars']),125)

    def test_unchanged_target_preserves_existing_quantities(self):
        result=projection(self.row(),nav=Q(5000),target='.5',held_target='.5',execution_session='2025-01-02')
        self.assertEqual(set(result['targets']),{'2024-12-31/1'})

    def test_already_queued_exit_is_not_initially_bought(self):
        row=self.row();row['pending'].append({'operation':'CLOSE_POSITION','security_id':'A','slot_id':0})
        result=projection(row,nav=Q(5000),target='.5',held_target='0',execution_session='2025-01-02',initial=True)
        self.assertEqual(result['exits'],['2024-12-02/0']);self.assertNotIn('2024-12-02/0',result['targets'])

    def test_source_entry_budget_cannot_be_silently_changed(self):
        row=self.row();row['pending'][0]['intended_dollars']=100.
        with self.assertRaisesRegex(ValueError,'SOURCE_NAV20_ENTRY'):
            projection(row,nav=Q(5000),target='.5',held_target='0',execution_session='2025-01-02')

    def test_reference_gap_and_intraday_are_separate(self):
        row={'defensive_bar':{'open_signal':100.,'close_signal':101.,'close_adjusted':101.},
             'defensive_previous_bar':{'close_adjusted':50.}}
        self.assertEqual(defensive_factors(row),(Q(2),Q('1.01')))

    def test_carried_signal_uses_original_source_nav_but_current_funded_nav(self):
        row=self.row();row['pending'][0].update(signal_session='2024-12-30',intended_dollars=40.)
        result=projection(row,nav=Q(6000),target='.5',held_target='.5',execution_session='2025-01-02',source_navs={'2024-12-30':800.})
        self.assertEqual(Q(result['targets']['2024-12-30/1']['dollars']),150)
        self.assertEqual(result['opens']['2024-12-30/1']['origin_signal_session'],'2024-12-30')

    def test_future_source_signal_cannot_enter_projection(self):
        row=self.row();row['pending'][0]['signal_session']='2025-01-02'
        with self.assertRaisesRegex(ValueError,'FUTURE_CORE_SIGNAL'):
            projection(row,nav=Q(5000),target='.5',held_target='0',execution_session='2025-01-02')

    def test_financial_runtime_cannot_execute_locally(self):
        with self.assertRaisesRegex(ValueError,'LOCAL_FINANCIAL_INPUT_EXECUTION'):
            Runtime(model_sha256='0'*64,dataset_sha256='1'*64,profile_id='synthetic',protocol={})


if __name__=='__main__':unittest.main()
