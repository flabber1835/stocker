"""Run cash producer/reporting falsifiers in a disposable source copy only."""
from pathlib import Path
import subprocess
import sys


def main():
    prefix = 'tests/sentinel/test_alpaca_simulation_durability.py::'
    cases = [
        ('rounded-cursor', 'sentinel/execution/broker_cash.py',
         'balance_total = exact_decimal(running_total)',
         'balance_total = +exact_decimal(running_total)',
         'test_native_cash_accumulation_matches_sql_and_survives_restart[paper-28]'),
        ('rounded-external-capital', 'sentinel/core/cashflow.py',
         'return exact_decimal(sum((Fraction(f.amount)',
         'return +exact_decimal(sum((Fraction(f.amount)',
         'test_external_capital_and_reported_pl_keep_small_internal_income[28]'),
        ('rounded-pl-subtraction', 'sentinel/core/cashflow.py',
         'Fraction(closing_nav) - Fraction(opening_nav)',
         'Fraction(closing_nav - opening_nav)',
         'test_external_capital_and_reported_pl_keep_small_internal_income[28]'),
        ('rounded-residual-comparison', 'sentinel/core/cashflow.py',
         'abs(Fraction(residual)) > Fraction(tolerance)',
         'abs(residual) > tolerance',
         'test_nav_residual_just_outside_tolerance_stays_unexplained_after_restart'),
    ]
    for name, filename, before, after, test in cases:
        path = Path(filename)
        source = path.read_text()
        assert source.count(before) == 1, name
        try:
            path.write_text(source.replace(before, after))
            result = subprocess.run([sys.executable, '-m', 'pytest', prefix + test,
                '-q', '--tb=short', '-p', 'no:cacheprovider'], capture_output=True, text=True)
            print(name, 'exit', result.returncode, flush=True)
            print(result.stdout, flush=True)
            assert result.returncode == 1 and '1 failed' in result.stdout, result.stderr
            assert 'AssertionError' in result.stdout, result.stdout
        finally:
            path.write_text(source)
    print('4/4 producer/reporting mutants detected', flush=True)


if __name__ == '__main__':
    main()
