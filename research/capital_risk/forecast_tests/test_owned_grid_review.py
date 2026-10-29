"""Synthetic independent-equation falsifiers; no financial runtime calls."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from decimal import Decimal as D
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import owned_grid_review as review


class EquationTests(unittest.TestCase):
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
