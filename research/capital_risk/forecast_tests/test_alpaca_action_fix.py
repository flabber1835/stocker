"""Targeted pure input tests; no strategy/account transition."""
from decimal import Decimal
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parents[3]/'shared'))
from alpaca_fit_inputs import split_fact


class SplitInputFixTests(unittest.TestCase):
    def row(self,**changes):
        return {'id':'synthetic','symbol':'SYN','ex_date':'2025-01-02','old_rate':'1','new_rate':'2',**changes}

    def test_ambiguous_participant_is_quarantined_not_inferred(self):
        splits={};fact,reason=split_fact('forward_splits',self.row(alternate_symbol='OTHER'),{'2025-01-02'},splits)
        self.assertIsNone(fact);self.assertIn('participants',reason);self.assertEqual(splits,{})

    def test_duplicate_fact_does_not_double_entitlement(self):
        splits={}
        self.assertIsNone(split_fact('forward_splits',self.row(),{'2025-01-02'},splits)[1])
        self.assertIsNone(split_fact('forward_splits',self.row(id='duplicate'),{'2025-01-02'},splits)[1])
        self.assertEqual(splits,{('SYN','2025-01-02'):Decimal(2)})
        fact,reason=split_fact('forward_splits',self.row(id='conflict',new_rate='3'),{'2025-01-02'},splits)
        self.assertIsNone(fact);self.assertEqual(reason,'conflicting split terms')

    def test_off_calendar_economic_date_remains_unsupported(self):
        fact,reason=split_fact('forward_splits',self.row(ex_date='2025-01-04'),{'2025-01-02'}, {})
        self.assertIsNone(fact);self.assertIn('session',reason)

    def test_duplicate_multiplication_defect_is_detected(self):
        import alpaca_fit_inputs as inputs
        from sentinel.feed.alpaca_observation import stock_split
        from unittest.mock import patch
        def broken(kind,record,axis,splits):
            fact=stock_split(kind,record,axis=axis);key=(fact['ticker'],fact['date'])
            splits[key]=splits.get(key,Decimal(1))*Decimal(fact['ratio'])
            return fact,None
        result=unittest.TestResult()
        with patch(__name__+'.split_fact',broken):
            SplitInputFixTests('test_duplicate_fact_does_not_double_entitlement').run(result)
        self.assertFalse(result.wasSuccessful())


if __name__=='__main__':unittest.main()
