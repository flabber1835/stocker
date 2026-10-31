"""Pure first-suffix authority and selective snapshot guards, without replay."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT=Path(__file__).parents[1];sys.path.insert(0,str(ROOT))
import core_window_suffix_job as suffix
from core_window_review import first_difference


class SuffixGuards(unittest.TestCase):
    def test_baseline_resumes_own_checkpoint_and_other_arms_have_first_origins(self):
        for arm in ('B','B0','C','V'):
            args=suffix.financial_tail(arm,503)
            self.assertEqual(args[args.index('--max-transitions')+1],'629')
            self.assertEqual(args[args.index('--policy')+1],suffix.POLICIES[arm])
            self.assertEqual('--resume' in args,arm=='B')
            if arm=='B':self.assertEqual(args[args.index('--checkpoint')+1],'/out/run-001/checkpoint.json.gz')

    def test_unknown_disjoint_outputs_are_never_selected_for_snapshot(self):
        paths=dict(B=Path('b'),C=Path('unknown-writer'),V=Path('v'))
        selected=suffix.snapshot_outputs(Path('qual'),paths,dict(B=True,C=True),['C'])
        self.assertEqual(selected,[('QUAL',Path('qual')),('B',Path('b'))])
        self.assertNotIn(('V',Path('v')),selected)
        self.assertEqual(suffix.snapshot_outputs(Path('qual'),paths,{},['C']),[('QUAL',Path('qual'))])

    def test_unknown_snapshot_guard_removal_is_detected(self):
        with patch.object(suffix,'snapshot_outputs',lambda q,o,k,u:[('QUAL',q),*o.items()]):
            result=unittest.TestResult()
            SuffixGuards('test_unknown_disjoint_outputs_are_never_selected_for_snapshot').run(result)
        self.assertFalse(result.wasSuccessful())

    def test_request_cannot_substitute_qualification_or_periods(self):
        r=json.loads((ROOT/'core-window-suffix-request.json').read_bytes());suffix.validate_request(r)
        for change in (dict(stage='fresh-restart'),dict(qualification_source_commit='0'*40),dict(execution_sha256='0'*64)):
            with self.assertRaises(ValueError):suffix.validate_request({**r,**change})
        bad=deepcopy(r);bad['windows']['stress2021']['canonical_cases']=0
        with self.assertRaises(ValueError):suffix.validate_request(bad)

    def test_comparator_reports_exact_path_and_numeric_type_differences(self):
        a=dict(evidence=dict(cash=[dict(amount='50000')]))
        b=deepcopy(a);b['evidence']['cash'][0]['amount']='49999'
        self.assertEqual(first_difference(a,b),'$.evidence.cash[0].amount')
        self.assertEqual(first_difference(dict(x=1),dict(x=1.0)),'$.x')
        self.assertIsNone(first_difference(a,a))


if __name__=='__main__':unittest.main()
