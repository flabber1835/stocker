#!/usr/bin/env python3
"""Synthetic tests extracted from the generated source. Runs no historical replay."""
from __future__ import annotations
import argparse
import ast
import copy
from dataclasses import dataclass
import math
from pathlib import Path
from types import SimpleNamespace
import unittest

from experiment_overlay import ARMS, apply_arm, assert_arm_contract

BASE = ''


def loop_code(source: str, marker: str):
    tree = ast.parse(source)
    nodes = [n for n in ast.walk(tree) if isinstance(n, ast.For)
             and isinstance(n.target, ast.Name) and n.target.id == 's'
             and ast.unparse(n.iter) == 'book.slots'
             and marker in ast.get_source_segment(source, n)]
    if len(nodes) != 1:
        raise AssertionError(f'Expected one actual source loop for {marker}: {len(nodes)}')
    return compile(ast.fix_missing_locations(ast.Module(body=[nodes[0]], type_ignores=[])), '<generated-loop>', 'exec')


def fixture(source: str):
    ns = {'__name__': __name__, 'dataclass': dataclass,
          'np': SimpleNamespace(nan=float('nan')), 'finite': math.isfinite,
          'math': math, 'COST': .001, 'COOLDOWN': 21, 'REVIEW_AGE': 119, 'STOP_RET': .70}
    slot = next(n for n in ast.parse(source).body if isinstance(n, ast.ClassDef) and n.name == 'Slot')
    exec(compile(ast.fix_missing_locations(ast.Module(body=[slot], type_ignores=[])), '<Slot>', 'exec'), ns)
    s = ns['Slot'](tid=0, qty=10., entry_sig=100., peak=100., entry_day=0)
    ns.update(book=SimpleNamespace(slots=[s], cash=0., sec_ready={}, terminal_pending={}, last_raw={}),
              gday=100, clsig=[60.], inpool=[False], recent=[-.1], opraw=[60.], volume=[100.],
              sells=0, stop_days=[], _exit_delay_events=[], sid=['synthetic-0'], tick=['SYNTHETIC'], ds='test-session')
    return ns, s


class ExitDelayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.variant = apply_arm(BASE, 'EXIT_DELAY_1')
        cls.close_code = loop_code(cls.variant, "s.sell_reason='review'")
        cls.open_code = loop_code(cls.variant, 's.held() and s.pending_sell')

    def setUp(self):
        self.ns, self.s = fixture(self.variant)

    def close(self, day, price=60.):
        self.ns.update(gday=day, clsig=[price])
        exec(self.close_code, self.ns)

    def opened(self, day, price=60., volume=100.):
        self.ns.update(gday=day, opraw=[price], volume=[volume])
        exec(self.open_code, self.ns)

    def test_stop_waits_one_extra_session_and_repeated_signal_keeps_first_time(self):
        self.close(100)
        self.opened(101)
        self.assertTrue(self.s.held())
        self.close(101)
        self.assertEqual(self.s.pending_exit_signal_day, 100)
        self.opened(102)
        self.assertFalse(self.s.held())
        self.assertAlmostEqual(self.ns['book'].cash, 10 * 60 * .999)
        self.assertEqual(self.ns['sells'], 1)
        self.assertEqual(self.ns['_exit_delay_events'][0]['signal_session_index'], 100)
        self.assertEqual(self.ns['_exit_delay_events'][0]['execution_session_index'], 102)
        self.assertEqual(self.ns['book'].sec_ready[0], 123)

    def test_review_waits_one_extra_session(self):
        self.s.entry_day = -20
        self.close(100, 90.)
        self.assertEqual(self.s.sell_reason, 'review')
        self.opened(101, 90.)
        self.close(101, 90.)
        self.opened(102, 90.)
        self.assertFalse(self.s.held())
        self.assertEqual(self.ns['stop_days'], [])

    def test_review_to_stop_changes_reason_and_preserves_first_time(self):
        self.s.entry_day = -20
        self.close(100, 90.)
        self.opened(101)
        self.close(101, 60.)
        self.assertEqual(self.s.sell_reason, 'stop')
        self.assertEqual(self.s.pending_exit_signal_day, 100)
        self.opened(102)
        self.assertEqual(self.ns['stop_days'], [102])

    def test_price_recovery_does_not_cancel_pending_order(self):
        self.close(100)
        self.opened(101)
        self.close(101, 110.)
        self.opened(102, 110.)
        self.assertEqual(self.ns['sells'], 1)
        self.assertAlmostEqual(self.ns['book'].cash, 10 * 110 * .999)

    def test_unavailable_open_retries_and_timer_does_not_restart(self):
        for px, vol in ((float('nan'), 100.), (0., 100.), (60., 0.)):
            with self.subTest(price=px, volume=vol):
                self.ns, self.s = fixture(self.variant)
                self.close(100)
                self.opened(101)
                self.close(101)
                self.opened(102, px, vol)
                self.assertTrue(self.s.held())
                self.close(102)
                self.opened(103)
                self.assertEqual(self.ns['sells'], 1)
                self.assertEqual(self.ns['_exit_delay_events'][0]['signal_session_index'], 100)

    def test_invalid_or_same_session_signal_time_fails_closed(self):
        for invalid in (-1, 101, 102):
            with self.subTest(timestamp=invalid):
                self.ns, self.s = fixture(self.variant)
                self.s.pending_sell = True
                self.s.pending_exit_signal_day = invalid
                with self.assertRaisesRegex(RuntimeError, 'invalid latched'):
                    self.opened(101)

    def test_entry_timestamp_is_separate(self):
        self.s.pending_signal_day = 7
        self.close(100)
        self.assertEqual(self.s.pending_signal_day, 7)
        self.opened(102)
        self.assertEqual(self.s.pending_signal_day, 7)
        self.assertEqual(self.s.pending_exit_signal_day, -1)

    def test_slot_reuse_starts_a_new_exit_clock(self):
        self.close(100)
        self.opened(102)
        self.s.tid = 0; self.s.qty = 10.; self.s.entry_sig = 100.; self.s.peak = 100.; self.s.entry_day = 123
        self.close(124)
        self.assertEqual(self.s.pending_exit_signal_day, 124)
        self.opened(125)
        self.assertTrue(self.s.held())
        self.opened(126)
        self.assertEqual(self.ns['sells'], 2)

    def test_entry_execution_keeps_its_original_timing(self):
        code = loop_code(self.variant, 's.reserved() and not s.held()')
        self.s.tid=-1; self.s.qty=0.; self.s.pending_tid=0; self.s.pending_shares=10.; self.s.pending_signal_day=100
        self.s.pending_exit_signal_day=55
        self.ns.update(gday=101, opsig=[60.], buys=0)
        self.ns['book'].cash=1000.
        exec(code, self.ns)
        self.assertTrue(self.s.held())
        self.assertEqual(self.s.entry_day, 101)
        self.assertEqual(self.s.pending_exit_signal_day, -1)

    def test_terminal_blocks_unchanged_except_exit_timestamp_reset(self):
        def blocks(src):
            return [n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.For)
                    and (('for s in book.slots:' in ast.get_source_segment(src, n)
                          and 'term_tids' in ast.get_source_segment(src, n)
                          and ast.unparse(n.iter) == 'book.slots')
                         or ast.unparse(n.iter) == 'list(book.terminal_pending)')]
        class StripTimestamp(ast.NodeTransformer):
            def visit_Assign(self, node):
                if any(isinstance(t, ast.Attribute) and t.attr == 'pending_exit_signal_day' for t in node.targets):
                    return None
                return self.generic_visit(node)
        b, v = blocks(BASE), blocks(self.variant)
        self.assertEqual(len(b), 2)
        self.assertEqual(len(v), 2)
        self.assertEqual([ast.dump(n) for n in b],
                         [ast.dump(StripTimestamp().visit(copy.deepcopy(n))) for n in v])

    def test_signal_zero_and_year_boundary_are_global_session_indices(self):
        for day in (0, 251, 252, 5030):
            with self.subTest(day=day):
                self.ns, self.s = fixture(self.variant)
                self.s.entry_day=day-1
                self.close(day)
                self.opened(day+1)
                self.close(day+1)
                self.opened(day+2)
                self.assertEqual(self.ns['sells'], 1)

    def test_all_six_variants_compile(self):
        for arm in ARMS:
            compile(apply_arm(BASE, arm), arm, 'exec')

    def test_contract_rejects_dividend_regression_and_clock_reset(self):
        bad = self.variant.replace('gday+1,q*rawdiv', 'gday+15,q*rawdiv')
        with self.assertRaises(RuntimeError):
            assert_arm_contract(BASE, bad, 'EXIT_DELAY_1')
        bad = self.variant.replace('gday if not s.pending_sell else s.pending_exit_signal_day', 'gday')
        with self.assertRaises(RuntimeError):
            assert_arm_contract(BASE, bad, 'EXIT_DELAY_1')

    def test_contract_rejects_missing_delay_reset_or_aliased_entry_time(self):
        for old, new in (('if gday < s.pending_exit_signal_day+2: continue', 'if gday < s.pending_exit_signal_day+1: continue'),
                         ('s.pending_exit_signal_day=-1', 's.pending_exit_signal_day=0'),
                         ('s.pending_signal_day=gday', 's.pending_signal_day=gday+1')):
            with self.subTest(mutation=old):
                with self.assertRaises(RuntimeError):
                    assert_arm_contract(BASE, self.variant.replace(old,new), 'EXIT_DELAY_1')


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--base', required=True, type=Path)
    args=p.parse_args()
    BASE=args.base.read_text()
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ExitDelayTests))
    raise SystemExit(0 if result.wasSuccessful() else 1)
