"""Static/private compilation and existing fence guards; no financial replay."""
from pathlib import Path
import ast
import json
import sys
import unittest
from unittest.mock import patch

ROOT=Path(__file__).parents[1];sys.path.insert(0,str(ROOT))
import concentration_build as c
from concentration_review import committed_prefix
from baseline_prefix import worker_arm,worker_stage

class ConcentrationQuarterGuards(unittest.TestCase):
    def test_dated_edit_changes_only_private_backtest(self):
        line="START, END, MEASURED_CLOSES = _CORE_WINDOWS[os.environ['CAPITAL_RISK_WINDOW']]"
        files={c.BACKTEST:('import os\n_CORE_WINDOWS={}\n'+line+'\n').encode(),'other.py':b'unchanged\n'}
        with patch.object(c,'render',return_value=files):out=c.render_quarter({},risk=True)
        self.assertEqual(out['other.py'],files['other.py'])
        self.assertIn("'concentration-q1-2025']=('2025-01-02','2025-03-31',60)",out[c.BACKTEST].decode())
        ast.parse(out[c.BACKTEST])
        with patch.object(c,'render',return_value={c.BACKTEST:b'wrong boundary'}):
            with self.assertRaisesRegex(ValueError,'PATCH_SITE_COUNT'):c.render_quarter({},risk=True)

    def test_new_names_allow_only_B_B0_C_and_exact_phases(self):
        for arm in ('b','b0','c'):
            name='capital-risk-core-window-cq12025-'+arm+'-123-1'
            self.assertEqual(worker_arm(name),arm.upper());self.assertEqual(worker_stage(name),'short-core-window')
            for suffix in ('-input','-review'):self.assertEqual(worker_stage(name+suffix),'short-core-window')
        for name in ('capital-risk-core-window-cq12025-v-123-1','capital-risk-core-window-cq12025-c-123-1-retry',
                     'paper-core-window-cq12025-c-123-1','capital-risk-core-window-cq12024-c-123-1'):
            with self.assertRaises(ValueError):worker_stage(name)

    def test_quarter_protocol_is_fixed_and_new_origins_required(self):
        p=json.loads((ROOT/'concentration-quarter-protocol.json').read_bytes())
        self.assertEqual(p['window'],['2025-01-02','2025-03-31',60]);self.assertEqual(p['arms'],['B','B0','C'])
        self.assertEqual(p['capital'],'50000');self.assertEqual((p['feature_sessions'],p['formation_sessions']),(299,126))
        self.assertTrue(p['own_fresh_origin_each_arm']);self.assertTrue(p['original_factor_parameters_unchanged'])
        self.assertEqual(p['worker_wait_seconds'],1200);self.assertEqual(p['workflow_timeout_minutes'],45)
        for key in ('production_contacted','automatic_extension','parameter_sweep','plaintext_financial_publication'):
            self.assertFalse(p[key])

    def test_review_has_committed_prefix_and_no_tail_recovery_mutation(self):
        source=(ROOT/'concentration_review.py').read_text()
        ast.parse(source)
        raw=b'{"session":"a"}\n{"unsent":"b"}\n';size=16
        prefix,tail=committed_prefix(raw,size)
        self.assertEqual(prefix,b'{"session":"a"}\n');self.assertEqual(tail['bytes'],len(raw)-size)
        self.assertEqual(raw,b'{"session":"a"}\n{"unsent":"b"}\n')
        for size in (-1,True,len(raw)+1,2):
            with self.assertRaises(ValueError):committed_prefix(raw,size)
        self.assertIn('REFUSED_C_QUARTER_COMPLETE_TAIL',source)
        self.assertIn('REFUSED_C_QUARTER_ACCOUNTING_BINDING',source)
        self.assertIn('canonical_roundtrips=True',source)
        self.assertNotIn('journal.recover(',source)

if __name__=='__main__':unittest.main()
