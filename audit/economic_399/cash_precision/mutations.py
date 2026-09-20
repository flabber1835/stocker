"""Run only in a disposable source copy; verify cash authority falsifiers."""
from pathlib import Path
import subprocess
import sys


def main():
    path = Path('sentinel/paper/cash.py')
    original = path.read_text()
    tests = 'tests/sentinel/test_cash_grace_identity.py::'
    cases = [
        ('rounded-comparison',
         'abs(Fraction(account.cash) - exact_expected) > 1',
         'abs(account.cash - expected) > Decimal("1.00")',
         'test_default_precision_cannot_admit_cash_just_outside_tolerance'),
        ('rounded-fill-product',
         'Fraction(command.filled_quantity) * Fraction(command.filled_average_price)',
         'Fraction(command.filled_quantity * command.filled_average_price)',
         'test_default_precision_cannot_admit_cash_just_outside_tolerance'),
        ('missing-activity-delta',
         'exact_expected = expected_without_activity + activity_delta',
         'exact_expected = expected_without_activity',
         'test_activity_delta_cannot_round_cash_into_tolerance'),
        ('rounded-grace-identity',
         'account=account, expected_cash=expected,',
         'account=account, expected_cash=+expected,',
         'test_changed_decimal_context_cannot_renew_cash_grace'),
    ]
    try:
        for name, before, after, test in cases:
            assert original.count(before) == 1, name
            path.write_text(original.replace(before, after))
            result = subprocess.run([sys.executable, '-m', 'pytest', tests + test,
                '-q', '--tb=short', '-p', 'no:cacheprovider'], capture_output=True, text=True)
            print(name, 'exit', result.returncode, flush=True)
            print(result.stdout, flush=True)
            assert result.returncode == 1 and '1 failed' in result.stdout, result.stderr
            assert ('DID NOT RAISE' in result.stdout or 'AssertionError' in result.stdout), result.stdout
    finally:
        path.write_text(original)
    print('4/4 cash authority mutants detected', flush=True)


if __name__ == '__main__':
    main()
