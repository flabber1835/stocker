import sys,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).parents[1];sys.path.insert(0,str(ROOT))
from weighted_account_adapter import account_step

class ReportingAdapterTests(unittest.TestCase):
    def test_carries_only_prior_reporting_fields(self):
        prior=dict(research_entry_mode='FORMED_BASKET',measurement_anchor_session='2008-02-22')
        returned=dict(strategy_nav='51000',gross_factor='1.02',net_factor='1.019',held_allocation='0.55')
        with patch('weighted_account_adapter.advance_account',return_value=returned):
            actual=account_step(prior,{},.55,None)
        self.assertEqual({k:actual[k] for k in returned},returned)
        self.assertEqual(actual,{**returned,**prior});self.assertNotIn('research_entry_mode',returned)

    def test_does_not_fabricate_missing_reporting_origin(self):
        with patch('weighted_account_adapter.advance_account',return_value=dict(strategy_nav='50000')):
            with self.assertRaises(ValueError):account_step({}, {},0,None)
            with self.assertRaises(ValueError):account_step(dict(research_entry_mode='FORMED_BASKET',measurement_anchor_session='2006-01-01'),{},0,None)

if __name__=='__main__':unittest.main()
