"""Detect missing partial-notional, strict-residual and durable-union guards."""
import argparse
import subprocess
import sys

from tools.sentinel_rolling_storage_falsifiers import child

MUTANTS = {
    'partial_notional': ('sentinel.execution.fill_integrity',
        'if quantity < Fraction(order.filled_quantity) and gross[key] >= expected:',
        'if False:',
        'test_partial_native_notional_leaves_positive_economics_for_missing_shares[600-False]'),
    'positive_residual': ('sentinel.execution.fill_integrity',
        'and gross[key] >= expected:', 'and gross[key] > expected:',
        'test_partial_native_notional_leaves_positive_economics_for_missing_shares[500-False]'),
    'exact_product': ('sentinel.execution.fill_integrity',
        'Fraction(fill.quantity) * Fraction(fill.price)', 'Fraction(fill.quantity * fill.price)',
        'test_partial_native_notional_comparison_is_exact_under_low_decimal_precision[499.9999999999999999999999999999-True]'),
    'durable_union': ('sentinel.execution.reconcile',
        'fill_integrity.validate_durable(conn, observation, orders_by_broker_id)', 'pass',
        'test_partial_native_union_refuses_impossible_notional_and_recovers_after_restart[300]'),
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--child', choices=MUTANTS)
    args = parser.parse_args()
    if args.child:
        path = ('tests/sentinel/test_native_fill_acceptance.py'
                if args.child in {'partial_notional', 'positive_residual'}
                else 'tests/sentinel/test_native_fill_progression.py')
        return child(args.child, mutants=MUTANTS, test_file=path)
    failures = []
    for name in MUTANTS:
        result = subprocess.run([sys.executable, '-m', __spec__.name, '--child', name],
                                capture_output=True, text=True)
        killed = result.returncode == 1 and '1 failed' in result.stdout
        print(name + (': KILLED' if killed else ': NOT PROVED'), flush=True)
        print(result.stdout, flush=True)
        print(result.stderr, flush=True)
        if not killed:
            failures.append(name)
    return bool(failures)


if __name__ == '__main__':
    raise SystemExit(main())
