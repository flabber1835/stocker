"""Targeted pure input tests; no strategy/account transition."""
from decimal import Decimal
from pathlib import Path
import sys
import unittest
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parents[3]/'shared'))
from alpaca_fit_inputs import split_fact,cash_fact,cash_dependency_issues


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


class PendingCashInputTests(unittest.TestCase):
    def prior(self,*,held=False,queued=False,last='2024-12-31'):
        return SimpleNamespace(wealth_core={'episodes':{'0':{'security_id':'SYN'}} if held else {}},
            pending=[{'operation':'OPEN_SLOT_POSITION','security_id':'SYN'}] if queued else [],last_processed_session=last)

    def issue(self,day='2025-01-04',rate='1'):
        record={'id':'synthetic-cash','symbol':'SYN','ex_date':day,'rate':rate,'foreign':False,'currency':'USD'}
        fact,issue=cash_fact(record,{'2025-01-02','2025-01-03','2025-01-06'})
        self.assertIsNone(fact);issue['security_ids']=['SYN'];return issue

    def test_uncertain_cash_blocks_only_affected_dependencies(self):
        issue=self.issue();self.assertIsNone(issue['trusted_ex_session'])
        self.assertEqual(cash_dependency_issues(self.prior(),[issue],'2025-01-06'),[])
        self.assertEqual(cash_dependency_issues(self.prior(held=True),[issue],'2025-01-06'),['synthetic-cash'])
        self.assertEqual(cash_dependency_issues(self.prior(queued=True),[issue],'2025-01-06'),['synthetic-cash'])

    def test_known_ex_session_requires_actual_ownership_interval(self):
        issue=self.issue(day='2025-01-02',rate=None)
        self.assertEqual(issue['trusted_ex_session'],'2025-01-02')
        self.assertEqual(cash_dependency_issues(self.prior(held=True),[issue],'2025-01-02'),['synthetic-cash'])
        self.assertEqual(cash_dependency_issues(self.prior(held=True,last='2025-01-03'),[issue],'2025-01-06'),[])

    def test_pending_cash_guard_removal_is_detected(self):
        from unittest.mock import patch
        result=unittest.TestResult()
        with patch(__name__+'.cash_dependency_issues',lambda *args:[]):
            PendingCashInputTests('test_uncertain_cash_blocks_only_affected_dependencies').run(result)
        self.assertFalse(result.wasSuccessful())


if __name__=='__main__':unittest.main()
