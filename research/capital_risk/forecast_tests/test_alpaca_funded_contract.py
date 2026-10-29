"""Only hand-valued geometry, evidence equations and boundary falsifiers."""
from copy import deepcopy
from fractions import Fraction as Q
import hashlib
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from test_alpaca_account_geometry import AccountGeometryTests
from alpaca_fit_funded_review import expected_pending,rounded_rational,fill_signature,treatment_days
from risk_review_math import equation,digest


class FundedReviewContract(unittest.TestCase):
    def test_integer_rounding_ties_and_half_unit_bound(self):
        for units,expected in [(2,2),(3,4)]:
            value=Q(2*units+1,2*10**24)
            self.assertEqual(rounded_rational(value),Q(expected,10**24))
        self.assertLessEqual(abs(rounded_rational(Q(1,3))-Q(1,3)),Q('5e-25'))

    def test_independent_projection_agrees_with_hand_value_not_future_close(self):
        row=AccountGeometryTests().row();source=SimpleNamespace(navs={row['session']:1000.})
        value=expected_pending(row,source,Q(5000),'.5','0','2025-01-02',True)
        self.assertEqual(Q(value['targets']['2024-12-02/0']['dollars']),250)
        self.assertEqual(Q(value['targets']['2024-12-31/1']['dollars']),125)
        changed=deepcopy(row);changed['pending'][0]['intended_dollars']=100.
        with self.assertRaisesRegex(ValueError,'ORIGINAL_ENTRY_BUDGET'):
            expected_pending(changed,source,Q(5000),'.5','0','2025-01-02',True)

    def test_economic_mutations_cannot_pass_event_equation(self):
        before={'schema_id':'research.persistent-funded-account-prototype/2','source_sha256':'a'*64,'cash':'1000',
            'positions':{},'claims':{},'retired':[],'applied_events':[],'last_session':None,'chain_sha256':'0'*64}
        event={'event_id':'toy','session':'2025-01-02','operation':'BUY','episode':'old/0','security_id':'A',
            'raw_price':'50','requested_shares':'5','filled_shares':'5','fees':'1/4','outcome':'FILLED'}
        after={**before,'cash':'2999/4','positions':{'old/0':{'episode':'old/0','security_id':'A','ticker':'A','kind':'EQUITY','shares':'5'}},
            'applied_events':['toy'],'last_session':'2025-01-02'}
        record={'event':event,'cash_before':'1000','cash_after':'2999/4','state_without_chain':{k:v for k,v in after.items() if k!='chain_sha256'}}
        record['chain_sha256']=digest({'previous':before['chain_sha256'],'record':record})
        observed={'record':record,'context':{'signal_session':'2024-12-31','core_exit':False}}
        result=equation(before,observed,{'old/0':{'ticker':'A'}},{'A':{'raw_open':'50'}},{})
        self.assertEqual(Q(result[0]['cash']),Q('749.75'))
        for path,value in [('fees','0'),('raw_price','60'),('filled_shares','6')]:
            wrong=deepcopy(observed);wrong['record']['event'][path]=value
            with self.assertRaises(ValueError):equation(before,wrong,{'old/0':{'ticker':'A'}},{'A':{'raw_open':'50'}},{})
        wrong=deepcopy(observed);wrong['record']['state_without_chain']['cash']='1000'
        with self.assertRaises(ValueError):equation(before,wrong,{'old/0':{'ticker':'A'}},{'A':{'raw_open':'50'}},{})


class FundedTreatmentContract(unittest.TestCase):
    def test_avoiding_a_baseline_positive_fill_is_real_treatment(self):
        self.assertEqual(treatment_days({'day':[]},{'day':[('lot','BUY','3','50','3/20')]}),1)

    def test_only_changing_a_diagnostic_cause_is_not_treatment(self):
        f={'episode':'lot','side':'BUY','filled_shares':'3','raw_open':'50','fees':'3/20','cause':'GLOBAL'}
        other={**f,'cause':'INITIAL'}
        self.assertEqual(treatment_days({'day':fill_signature([f])},{'day':fill_signature([other])}),0)

    def test_zero_share_intents_are_not_funded_treatment(self):
        f={'episode':'lot','side':'BUY','filled_shares':'0','raw_open':'50','fees':'0','cause':'GLOBAL'}
        self.assertEqual(treatment_days({'day':fill_signature([f])},{'day':[]}),0)
        with self.assertRaisesRegex(ValueError,'TREATMENT_COMMON_DATES'):treatment_days({'first':[]},{'other':[]})


if __name__=='__main__':unittest.main()
