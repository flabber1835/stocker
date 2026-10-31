"""Pure source-context examples; no Core/account transition."""
from decimal import Decimal
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parents[3]/'shared'))
import alpaca_fit_inputs as inputs


class SplitContextTests(unittest.TestCase):
    def data(self,packed):
        data=inputs.Inputs.__new__(inputs.Inputs);data.packed=packed;data.admission_context=inputs.SPLIT_CONTEXT
        data.sids=['S'];data.assets={'S':{'ticker':'SYN'}};data.sid_index={'S':0}
        days=['2024-08-01','2024-08-02','2024-08-05','2024-08-06'];data.index={d:i for i,d in enumerate(days)}
        data.values=np.array([[[10.,10.,100.,100.],[100.,100.,100.,100.],[100.,100.,100.,100.],[100.,100.,100.,100.]]])
        data.present=np.ones((1,4,2),dtype=bool);data.undated={};data.resets={};data.dividend_by_symbol={}
        data.splits={('SYN','2024-08-02'):Decimal('.1')};data.split_by_symbol={'SYN':{('SYN','2024-08-02'):'.1'}}
        return data,days[1:]

    def test_actual_adjacent_context_is_used_and_feature_start_clipped(self):
        for packed in (False,True):
            data,days=self.data(packed);found,_=data.admitted(days)
            self.assertEqual(found,{'S':days[0]});self.assertEqual(len(days),3)
            data.admission_context=None;found,why=data.admitted(days)
            self.assertEqual(found,{});self.assertEqual(why,{'split_predecessor_missing':1})

    def test_missing_predecessor_keeps_existing_refusal(self):
        for packed in (False,True):
            data,days=self.data(packed);data.present[0,0,1]=False
            found,why=data.admitted(days)
            self.assertEqual(found,{});self.assertEqual(why,{'split_predecessor_missing':1})

    def test_conflicting_adjustment_is_not_hidden_by_context(self):
        data,days=self.data(True);data.values[0,2,3]=90.
        found,why=data.admitted(days)
        self.assertEqual(found,{});self.assertEqual(why,{'adjustment_discontinuity':1})

    def test_unknown_context_policy_refuses_and_guard_removal_is_detected(self):
        with self.assertRaisesRegex(ValueError,'ADMISSION_CONTEXT_POLICY'):inputs.context_policy('UNKNOWN')
        original=inputs.need
        with patch.object(inputs,'need',side_effect=lambda v,r:None if r=='ADMISSION_CONTEXT_POLICY' else original(v,r)):
            self.assertEqual(inputs.context_policy('UNKNOWN'),'UNKNOWN')


if __name__=='__main__':unittest.main()
