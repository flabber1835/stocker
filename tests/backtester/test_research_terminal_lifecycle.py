"""Terminal witness regression: ARXX and causal retirement invariants."""
import csv
import gzip
import math
from pathlib import Path
import tempfile
import unittest

from backtester.research_terminal_lifecycle import (
    LeadershipReturnUnresolved, _once, leadership_return, terminal_index,
)


def event(**updates):
    row = dict(security_id='ARXX-SID', effective_session='2007-08-15',
               disposition='EXACT_EVIDENCE', authority='FROZEN_PRIMARY_TERMS',
               evidence_hash='a' * 64, kind='CASH_MERGER', cash_per_share='14.5')
    row.update(updates)
    return row


def value(**updates):
    args = dict(security_id='ARXX-SID', session='2007-08-15',
                prior_signal=14.0, current_signal=14.35, prior_raw=14.0,
                terminal=event())
    args.update(updates)
    return leadership_return(**args)


class TerminalLeadershipTests(unittest.TestCase):
    def test_arxx_exact_cash_merger(self):
        result, source = value()
        self.assertAlmostEqual(result, 14.5 / 14 - 1)
        self.assertEqual(source, 'EXACT_TERMINAL_CONSIDERATION')

    def test_arxx_terminal_can_replace_absent_close(self):
        self.assertEqual(value(current_signal=None), value())

    def test_observed_return_unchanged(self):
        self.assertEqual(value(terminal=None), (14.35 / 14 - 1, 'OBSERVED_SIGNAL_CLOSE'))

    def test_split_domain_uses_raw_prior(self):
        self.assertEqual(value(prior_signal=7), value())

    def test_writeoff_has_real_loss(self):
        self.assertEqual(value(terminal=event(kind='WRITE_OFF'))[0], -1.0)

    def test_zero_cash_terms_are_explicit(self):
        self.assertEqual(value(terminal=event(cash_per_share='0'))[0], -1.0)

    def test_conversion_preserves_fractional_witness(self):
        result, _ = value(terminal=event(kind='CONVERSION', delivered_security_id='NEW', exchange_ratio='.52'), delivered_raw=65.63)
        self.assertAlmostEqual(result, .52 * 65.63 / 14 - 1)

    def test_mixed_consideration(self):
        result, _ = value(terminal=event(kind='CASH_PLUS_STOCK', delivered_security_id='NEW', exchange_ratio='.52', cash_per_share='16.5'), delivered_raw=65.63)
        self.assertAlmostEqual(result, (16.5 + .52 * 65.63) / 14 - 1)

    def test_missing_ordinary_close_fails(self):
        with self.assertRaises(LeadershipReturnUnresolved):
            value(terminal=None, current_signal=None)

    def test_incomplete_terminal_missing_close_fails(self):
        with self.assertRaises(LeadershipReturnUnresolved):
            value(terminal=event(disposition='INCOMPLETE'), current_signal=math.nan)

    def test_incomplete_terminal_observed_close(self):
        self.assertEqual(value(terminal=event(disposition='INCOMPLETE'))[0], 14.35 / 14 - 1)

    def test_future_terms_rejected(self):
        with self.assertRaises(LeadershipReturnUnresolved):
            value(terminal=event(effective_session='2007-08-16'))

    def test_past_terms_cannot_be_reapplied(self):
        with self.assertRaises(LeadershipReturnUnresolved):
            value(session='2007-08-16')

    def test_different_security_rejected(self):
        with self.assertRaises(LeadershipReturnUnresolved):
            value(terminal=event(security_id='OTHER'))

    def test_missing_authority_rejected(self):
        with self.assertRaises(LeadershipReturnUnresolved):
            value(terminal=event(authority=''))

    def test_missing_evidence_hash_rejected(self):
        with self.assertRaises(LeadershipReturnUnresolved):
            value(terminal=event(evidence_hash=''))

    def test_invalid_prior_raw_rejected(self):
        for bad in (None, 0, -1, math.nan, math.inf):
            with self.subTest(bad=bad), self.assertRaises(LeadershipReturnUnresolved):
                value(prior_raw=bad)

    def test_invalid_prior_signal_rejected(self):
        for bad in (None, 0, -1, math.nan, math.inf):
            with self.subTest(bad=bad), self.assertRaises(LeadershipReturnUnresolved):
                value(prior_signal=bad)

    def test_invalid_cash_terms_rejected(self):
        for bad in (None, -1, math.nan, math.inf):
            with self.subTest(bad=bad), self.assertRaises(LeadershipReturnUnresolved):
                value(terminal=event(cash_per_share=bad))

    def test_missing_delivery_mark_rejected(self):
        with self.assertRaises(LeadershipReturnUnresolved):
            value(terminal=event(kind='CONVERSION', delivered_security_id='NEW', exchange_ratio='.52'))

    def test_missing_delivery_identity_rejected(self):
        with self.assertRaises(LeadershipReturnUnresolved):
            value(terminal=event(kind='CONVERSION', exchange_ratio='.52'), delivered_raw=65.63)

    def test_unknown_exact_kind_rejected(self):
        with self.assertRaises(LeadershipReturnUnresolved):
            value(terminal=event(kind='UNRECOGNIZED'))

    def test_terminal_same_session_split_basis(self):
        self.assertAlmostEqual(value(split_ratio=2.0)[0], 29.0 / 14.0 - 1.0)

    def test_original_cohort_weight_preserved(self):
        # The terminated member earns its return in the existing denominator.
        returns = [value()[0], .01, -.02]
        self.assertAlmostEqual(sum(returns) / 3, ((14.5 / 14 - 1) + .01 - .02) / 3)

    def test_seam_requires_exactly_one_match(self):
        for text in ('none', 'xx'):
            with self.assertRaises(RuntimeError):
                _once(text, 'x', 'y', 'test')
        self.assertEqual(_once('axb', 'x', 'y', 'test'), 'ayb')

    def test_index_lookup_is_session_scoped(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            row = event()
            with gzip.open(path / 'terminal-events.csv.gz', 'wt', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=list(row))
                writer.writeheader(); writer.writerow(row)
            index = terminal_index(path)
            self.assertEqual(index.get('2007-08-14', {}), {})
            self.assertEqual(index['2007-08-15']['ARXX-SID'], row)
            self.assertEqual(index.get('2007-08-16', {}), {})

    def test_conflicting_terminal_records_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory); row = event()
            with gzip.open(path / 'terminal-events.csv.gz', 'wt', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=list(row)); writer.writeheader()
                writer.writerow(row); writer.writerow(event(cash_per_share='999'))
            with self.assertRaises(LeadershipReturnUnresolved):
                terminal_index(path)


if __name__ == '__main__':
    unittest.main()
