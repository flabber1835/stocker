"""Behavioral regression tests for explicit best-effort assumptions."""
from pathlib import Path
import gzip
import json
import tempfile
import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace
from backtester import research_best_effort as be

class BestEffortTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.audit=be.Audit(Path(self.tmp.name),'baseline')
        self.addCleanup(self.audit.close)
        self.args=dict(security_id='ARXX',session='2007-08-15',prior_signal=14.0,
                       current_signal=14.35,prior_raw=14.0,terminal=None,split_ratio=1.)
    def event(self,exact=False):
        return dict(security_id='ARXX',effective_session='2007-08-15',
                    disposition='EXACT_EVIDENCE' if exact else 'INCOMPLETE',cash_per_share=14.5)
    def test_exact_terms_delegate_unchanged(self):
        self.args['terminal']=self.event(True)
        strict=Mock(return_value=(14.5/14-1,'EXACT_TERMINAL_CONSIDERATION'))
        self.assertEqual(be.leadership_return(strict,audit=self.audit,**self.args)[0],14.5/14-1)
        strict.assert_called_once_with(**self.args)
    def test_exact_authority_failure_remains_failure(self):
        self.args['terminal']=self.event(True)
        with self.assertRaisesRegex(RuntimeError,'authority'):
            be.leadership_return(Mock(side_effect=RuntimeError('authority')),audit=self.audit,**self.args)
    def test_ordinary_return_delegates(self):
        strict=Mock(return_value=(.025,'OBSERVED_SIGNAL_CLOSE'))
        self.assertEqual(be.leadership_return(strict,audit=self.audit,**self.args),(.025,'OBSERVED_SIGNAL_CLOSE'))
        strict.assert_called_once_with(**self.args)
    def test_missing_close_carry_logged(self):
        self.args['current_signal']=float('nan')
        strict=Mock()
        self.assertEqual(be.leadership_return(strict,audit=self.audit,**self.args)[0],0.)
        strict.assert_not_called()
        self.assertEqual(self.audit.counts['MISSING_LEADERSHIP_CLOSE_CARRIED'],1)
    def test_missing_prior_signal_refused(self):
        self.args.update(prior_signal=None,current_signal=None)
        with self.assertRaises(ValueError): be.leadership_return(Mock(),audit=self.audit,**self.args)
    def test_unknown_terminal_baseline(self):
        self.args['terminal']=self.event()
        self.assertEqual(be.leadership_return(Mock(),audit=self.audit,**self.args)[0],0.)
    def test_haircut_scenarios(self):
        self.args['terminal']=self.event()
        for recovery,expected in ((1.,0.),(.5,-.5),(0.,-1.)):
            self.audit.config['terminal_recovery']=recovery
            self.assertEqual(be.leadership_return(Mock(),audit=self.audit,**self.args)[0],expected)
    def test_terminal_wrong_identity_refused(self):
        self.args['terminal']={**self.event(),'security_id':'OTHER'}
        with self.assertRaises(ValueError): be.leadership_return(Mock(),audit=self.audit,**self.args)
    def test_future_terminal_refused(self):
        self.args['terminal']={**self.event(),'effective_session':'2007-08-16'}
        with self.assertRaises(ValueError): be.leadership_return(Mock(),audit=self.audit,**self.args)
    def test_terminal_missing_prior_mark_refused(self):
        with self.assertRaises(ValueError): be.terminal_claim(100,None,1,1)
    def test_split_basis_terminal_claim(self):
        self.assertEqual(be.terminal_claim(200,10,2,.5),500)
        self.assertEqual(be.terminal_claim(50,10,.5,1),1000)
    def test_zero_recovery_is_explicit(self):
        self.assertEqual(be.terminal_claim(100,10,1,0),0.)
    def test_invalid_parameters_refused(self):
        for args in ((0,10,1,1),(10,0,1,1),(10,10,0,1),(10,10,1,1.1),(10,10,1,-.1)):
            with self.assertRaises(ValueError): be.terminal_claim(*args)
    def test_capacity_stays_pending_and_is_logged(self):
        strict=Mock(return_value=None)
        self.assertIsNone(be.capacity(strict,self.audit,100,[100]*20,security_id='X',session='2007-01-01',defer_excess=True))
        self.assertEqual(self.audit.counts['CAPACITY_DEFERRED'],1)
    def test_missing_capacity_authority_still_raises(self):
        with self.assertRaisesRegex(RuntimeError,'volume'):
            be.capacity(Mock(side_effect=RuntimeError('volume')),self.audit,10,[],security_id='X',session='2007-01-01')
    def test_unknown_inclusion_is_separate_scenario(self):
        self.assertFalse(be.SCENARIOS['baseline']['include_unknown'])
        self.assertTrue(be.SCENARIOS['unknown_inclusion']['include_unknown'])
        self.assertEqual(len(be.SCENARIOS),4)
    def test_assumptions_persist_valid_gzip(self):
        self.audit.event('UNKNOWN_PRICE_ELIGIBLE','2007-01-01',count=4)
        self.audit.close()
        with gzip.open(Path(self.tmp.name)/'assumptions.jsonl.gz','rt') as f:
            self.assertEqual(json.loads(f.readline())['count'],4)
        summary=json.loads((Path(self.tmp.name)/'assumption-audit.json').read_text())
        self.assertEqual(summary['affected_observations']['UNKNOWN_PRICE_ELIGIBLE'],4)
    def test_official_mode_refused(self):
        with patch.dict('os.environ',{'PIT_OFFICIAL_BACKTEST':'1'}):
            with self.assertRaisesRegex(RuntimeError,'PIT_OFFICIAL_BACKTEST=0'): be.run(SimpleNamespace())
    def test_source_seam_failures_are_not_suppressed(self):
        for text in ('','xx'):
            with self.assertRaises(RuntimeError): be.once(text,'x','z','seam')
    def test_comparison_missing_scenarios_explicit(self):
        self.assertEqual(be.compare(Path(self.tmp.name)),2)
        result=json.loads((Path(self.tmp.name)/'comparison-status.json').read_text())
        self.assertEqual(result['certification_status'],'NOT_CERTIFIED')
        self.assertEqual(len(result['missing_scenarios']),4)

if __name__=='__main__': unittest.main()
