"""Synthetic independent-equation falsifiers; no financial runtime calls."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from decimal import Decimal as D
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import owned_grid_review as review


class EquationTests(unittest.TestCase):
    def test_funded_startup_can_commit_nonzero_exposure_for_following_open(self):
        from owned_grid_worker import startup_projection
        previous={'pending_allocation':'0'}
        economics={'initial_deployment':True,'held_allocation':'0','pending_allocation':'1','strategy_nav':'49950',
            'gross_factor':'1','net_factor':'.999','transaction_cost_factor':'.999','turnover':'1'}
        candidate=startup_projection(economics,previous,.55,1)
        self.assertEqual(candidate['pending_allocation'],'0.55')
        self.assertEqual(economics['pending_allocation'],'1')
        self.assertEqual(candidate['held_allocation'],'0')
        row={'session':'2008-02-25','economics':economics}
        compact={'session':row['session'],'nav':'49950','gross':'1','net':'.999','cost':'.999',
            'turnover':'1','held':'0','pending':'0.55'}
        self.assertEqual(review.check_account(previous,row,compact,.55,1),candidate)
        with self.assertRaises(ValueError):startup_projection(economics,{'pending_allocation':'.25'},.55,1)

    def sample(self):
        previous={'held_allocation':'0.55','pending_allocation':'0.25','parent_core_close_equity':'100','strategy_nav':'50000'}
        row={'session':'2020-01-03','economics':{'parent_core_open_equity':'90','parent_core_close_equity':'95',
            'strategy_prices':{'bil_open_adjusted':'1','bil_close_adjusted':'1','bil_previous_close_adjusted':'1'}}}
        gross=(1+D('.55')*(D(90)/100-1))*(1+D('.25')*(D(95)/90-1));cost=1-D('.001')*D('.30');net=cost*gross
        record={'session':row['session'],'nav':str(D(50000)*net),'gross':str(gross),'net':str(net),'cost':str(cost),
            'turnover':'0.30','held':'0.25','pending':'0.55'}
        return previous,row,record

    def test_wrong_next_close_commitment_cannot_pass_correct_nav(self):
        previous,row,record=self.sample();review._P={'capital':'50000'}
        self.assertEqual(review.check_account(previous,row,record,.55,2)['pending_allocation'],'0.55')
        record['pending']='0.75'
        with self.assertRaisesRegex(ValueError,'EXPOSURE_LAG_AND_TARGET'):review.check_account(previous,row,record,.55,2)

    def test_next_close_guard_removal_is_detected(self):
        old=review.need
        with patch.object(review,'need',lambda v,r:None if r=='REVIEW_EXPOSURE_LAG_AND_TARGET' else old(v,r)):
            result=unittest.TestResult();EquationTests('test_wrong_next_close_commitment_cannot_pass_correct_nav').run(result)
        self.assertFalse(result.wasSuccessful())

    def test_nav_factor_cost_and_turnover_mutations_refuse(self):
        for key in ('nav','gross','net','cost','turnover'):
            with self.subTest(key=key):
                previous,row,record=self.sample();review._P={'capital':'50000'};record[key]=str(D(record[key])+D('.01'))
                with self.assertRaises(ValueError):review.check_account(previous,row,record,.55,2)


if __name__=='__main__':unittest.main()
