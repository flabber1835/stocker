"""Dependency-free dividend certification regressions; no historical replay."""
import ast
from types import SimpleNamespace
import unittest

from backtester.production_equivalent_economic_overlay import (
    DIVIDEND_LAG_SESSIONS,
    _align_dividend_summary,
    _dividend_due_lag,
    _force_one_session_dividend_lag,
    assert_contract,
    assert_one_session_dividend_lag,
)


def fixture(lag=1, summary_lag=1):
    return (
        'from backtester import champion_final_security_truth as _bestclass\n'
        'term_tids=()\n_leadership_terminal_tids=()\n'
        f'book.receivables.append((gday+{lag},q*rawdiv))\n'
        'open_eq,_=book.equity(opraw)\n'
        'eq,unresolved=book.equity(clraw)\n'
        f"summary={{'financial_grade_dividend_lag_sessions':{summary_lag}}}\n"
    )


class DividendLagTests(unittest.TestCase):
    def test_public_preflight_import_and_one_session(self):
        self.assertEqual(assert_one_session_dividend_lag(fixture()), 1)
        self.assertEqual(DIVIDEND_LAG_SESSIONS, 1)
        assert_contract(fixture())

    def test_exact_parser_distinguishes_one_and_fifteen(self):
        self.assertEqual(_dividend_due_lag(fixture()), 1)
        self.assertEqual(_dividend_due_lag(fixture(15, 15)), 15)

    def test_non_one_lags_fail_even_with_matching_summary(self):
        for lag in (0, 2, 10, 15, 100, 150):
            with self.subTest(lag=lag):
                with self.assertRaisesRegex(RuntimeError, 'dividend lag must be exactly 1 session'):
                    assert_contract(fixture(lag, lag))

    def test_boolean_float_variable_and_arithmetic_expressions_fail(self):
        for expr in ('gday+True', 'gday+1.0', 'gday+lag', 'gday+(1+0)', 'gday', 'other+1'):
            with self.subTest(expr=expr):
                with self.assertRaises(RuntimeError):
                    assert_one_session_dividend_lag(fixture().replace('gday+1', expr))

    def test_missing_duplicate_and_malformed_append_fail(self):
        for source in ('pass\n', fixture()+fixture(), 'book.receivables.append()\n',
                       'book.receivables.append(1)\n'):
            with self.subTest(source=source):
                with self.assertRaises(RuntimeError):
                    assert_one_session_dividend_lag(source)

    def test_comments_and_strings_cannot_prove_one_session(self):
        source = fixture(15, 15) + "# gday+1\nlabel='gday+1'\n"
        with self.assertRaisesRegex(RuntimeError, 'exactly 1 session'):
            assert_contract(source)

    def test_stale_summary_fails(self):
        with self.assertRaisesRegex(RuntimeError, 'summary disagrees'):
            assert_contract(fixture(1, 15))

    def test_missing_duplicate_and_noninteger_summary_fail(self):
        for source in (fixture().split('summary=')[0], fixture()+"extra={'financial_grade_dividend_lag_sessions':1}\n",
                       fixture().replace("sessions':1", "sessions':True")):
            with self.subTest(source=source):
                with self.assertRaises(RuntimeError):
                    assert_contract(source)

    def test_known_inherited_lag_and_summary_align(self):
        source = _align_dividend_summary(_force_one_session_dividend_lag(fixture(15, 15)))
        self.assertEqual(source, fixture())
        assert_contract(source)

    def test_alignment_is_idempotent(self):
        source = fixture()
        self.assertEqual(_force_one_session_dividend_lag(source), source)
        self.assertEqual(_align_dividend_summary(source), source)

    def test_unknown_inherited_lag_and_summary_are_rejected(self):
        with self.assertRaisesRegex(RuntimeError, 'unrecognized inherited dividend lag'):
            _force_one_session_dividend_lag(fixture(10, 10))
        with self.assertRaisesRegex(RuntimeError, 'unrecognized inherited dividend summary'):
            _align_dividend_summary(fixture(1, 10))

    def test_summary_rewrite_preserves_unrelated_constants_and_unicode(self):
        source = fixture(1, 15).replace('summary=', "label='euro €'; other=15; summary=")
        result = _align_dividend_summary(source)
        self.assertIn("label='euro €'; other=15;", result)
        assert_contract(result)

    def test_mutated_valid_source_is_rejected(self):
        source = fixture()
        assert_contract(source)
        with self.assertRaises(RuntimeError):
            assert_contract(source.replace('gday+1,', 'gday+15,'))

    def test_corrected_append_settles_next_session_and_conserves_value(self):
        source = _force_one_session_dividend_lag(fixture(15, 15))
        call = next(n for n in ast.walk(ast.parse(source)) if isinstance(n, ast.Call)
                    and isinstance(n.func, ast.Attribute) and n.func.attr == 'append')
        code = compile(ast.fix_missing_locations(ast.Module(body=[ast.Expr(value=call)], type_ignores=[])), '<dividend-append>', 'exec')
        book = SimpleNamespace(cash=100.0, receivables=[])
        env = {'book':book, 'gday':100, 'q':10.0, 'rawdiv':0.25}
        exec(code, env)
        self.assertEqual(book.receivables, [(101, 2.5)])
        self.assertEqual(book.cash, 100.0)
        # This is the same settlement expression used in the generated Book loop.
        settle = 'due=sum(a for dd,a in book.receivables if dd<=gday); book.cash+=due; book.receivables=[x for x in book.receivables if x[0]>gday]'
        exec(settle, env)
        self.assertEqual(book.cash, 100.0)
        total = book.cash + sum(a for _, a in book.receivables)
        env['gday'] = 101
        exec(settle, env)
        self.assertEqual(book.cash, 102.5)
        self.assertEqual(book.receivables, [])
        self.assertEqual(book.cash, total)
        exec(settle, env)
        self.assertEqual(book.cash, 102.5)


if __name__ == '__main__':
    unittest.main(verbosity=2)
