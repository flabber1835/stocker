"""Pure protocol/selection boundaries; no historical financial execution."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import owned_grid as grid


class OwnedGridTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import json
        cls.p=json.loads((Path(__file__).resolve().parents[1]/'sharadar-owned55-fit-protocol.json').read_bytes())
        cls.configs=grid.profiles(cls.p)

    def test_family_covers_nine_numeric_fields_and_current_rule(self):
        self.assertEqual(len(self.configs),26244)
        self.assertIn(grid.BASELINE,self.configs)
        self.assertEqual(set(self.p['grid']),set(grid.FIELDS))
        self.assertEqual(len({grid.identifier(c) for c in self.configs}),26244)

    def test_local_controller_and_account_execution_refuse_before_source_read(self):
        with patch.dict('os.environ',{'OWNED_GRID_HOSTED':''}):
            with self.assertRaisesRegex(ValueError,'LOCAL_CONTROLLER_OR_ACCOUNT_REPLAY'):
                grid.canonical_leaf('nonexistent','0'*64)
            from owned_grid_worker import canonical_account
            with self.assertRaisesRegex(ValueError,'LOCAL_CONTROLLER_OR_ACCOUNT_REPLAY'):
                canonical_account(None,None,None,None)

    def records(self):
        return [{'profile_id':grid.identifier(c),'period':'TRAINING','evaluation_metrics_included':False,
            'different_funded_training_exposure':False,'metrics':{'start':'2018-01-02','end':'2022-12-30',
                'closes':1259,'multiple':'2','cagr':.15,'maximum_drawdown_magnitude':'1/5'},'turnover':'1'} for c in self.configs]

    def test_selection_requires_all_profiles_and_rejects_later_metrics(self):
        rows=self.records()
        with self.assertRaisesRegex(ValueError,'SELECTION_COMPLETE_CLASS'):grid.select(rows[:-1],self.p)
        rows[0]['evaluation_metrics_included']=True
        with self.assertRaisesRegex(ValueError,'SELECTION_EVALUATION_LEAK'):grid.select(rows,self.p)

    def test_budget_winner_joint_gain_and_baseline_have_deterministic_priority(self):
        rows=self.records();winner=next(r for r in rows if r['profile_id']!=grid.identifier(grid.BASELINE))
        winner.update(different_funded_training_exposure=True,turnover='2')
        winner['metrics'].update(multiple='3',cagr=.24,maximum_drawdown_magnitude='1/10')
        result=grid.select(rows,self.p)
        self.assertEqual(result['selected'],[winner['profile_id']]);self.assertEqual(result['best_training_joint_gain'],winner['profile_id'])
        self.assertFalse(result['evaluation_used_for_selection'])

    def test_identical_funded_training_path_cannot_be_a_new_winner(self):
        rows=self.records();winner=next(r for r in rows if r['profile_id']!=grid.identifier(grid.BASELINE))
        winner['metrics'].update(multiple='20000000000000000000000001/10000000000000000000000000')
        result=grid.select(rows,self.p)
        self.assertEqual(result['selected'],[grid.identifier(grid.BASELINE)])

    def test_evaluation_leak_guard_removal_is_detected(self):
        import types
        old=grid.select;namespace={**old.__globals__,'need':lambda v,r:None};mutant=types.FunctionType(old.__code__,namespace)
        with patch.object(grid,'select',mutant):
            result=unittest.TestResult();OwnedGridTests('test_selection_requires_all_profiles_and_rejects_later_metrics').run(result)
        self.assertFalse(result.wasSuccessful())


if __name__=='__main__':unittest.main()
