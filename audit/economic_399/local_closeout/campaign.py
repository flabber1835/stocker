"""Offline exact-quantity falsifiers; mutate disposable copies only."""
from pathlib import Path
import subprocess
import sys

TESTS = ['tests/sentinel/test_nav_quantity_precision.py',
         'tests/sentinel/test_issue209_target_reprojection.py']
MUTANTS = (
    ('rounded_shadow_weight', 'sentinel/core/decision.py', (
        ('weights = _shadow_notionals(canonical, target, current_marks)',
         'weights = _shadow_weights(canonical, target, current_marks)'),
        ('weight_denominator=shadow_equity)', 'weight_denominator=Decimal(1))'),
    ), 'test_production_share_scaling_does_not_floor_a_rounded_weight'),
    ('rounded_opening_scale', 'sentinel/execution/opening_sizing.py', (
        ('account_quantity = Decimal((quantity * scale) // 1)',
         'account_quantity = Decimal((quantity * Fraction(display_decimal(scale))) // 1)'),
    ), 'test_opening_share_scaling_floors_once_after_exact_ratio'),
    ('rounded_core_floor', 'sentinel/execution/projection.py', (
        ('target_notional // (Fraction(price) * Fraction(lot))',
         'Fraction(display_decimal(target_notional / (Fraction(price) * Fraction(lot)))) // 1'),
    ), 'test_projection_never_rounds_unaffordable_fraction_up_to_one_share'),
    ('rounded_sleeve_floor', 'sentinel/execution/projection.py', (
        ('defensive_notional // (Fraction(price) * Fraction(lot))',
         'Fraction(display_decimal(defensive_notional / (Fraction(price) * Fraction(lot)))) // 1'),
    ), 'test_projection_never_rounds_unaffordable_fraction_up_to_one_share'),
    ('zero_denominator', 'sentinel/execution/projection.py', (
        ('if weight_denominator <= 0:', 'if False:'),
    ), 'test_projector_refuses_invalid_weight_denominator'),
    ('rounded_command_remainder', 'sentinel/execution/commands.py', (
        ('return exact_decimal(Fraction(self.quantity) - Fraction(self.filled_quantity))',
         'return self.quantity - self.filled_quantity'),
    ), 'test_partial_fill_remainder_is_not_rounded_into_an_overlapping_order'),
    ('rounded_broker_remainder', 'sentinel/execution/contract.py', (
        ('return exact_decimal(Fraction(self.quantity) - Fraction(self.filled_quantity))',
         'return self.quantity - self.filled_quantity'),
    ), 'test_partial_fill_remainder_is_not_rounded_into_an_overlapping_order'),
    ('rounded_signed_remainder', 'sentinel/execution/commands.py', (
        ('else self.remaining.copy_negate()', 'else -self.remaining'),
    ), 'test_partial_fill_remainder_is_not_rounded_into_an_overlapping_order'),
    ('rounded_committed_sum', 'sentinel/execution/commands.py', (
        ('return exact_decimal(total)', 'return +exact_decimal(total)'),
    ), 'test_committed_orders_do_not_erase_a_small_excess'),
    ('rounded_delta', 'sentinel/execution/commands.py', (
        ('remaining = exact_decimal(Fraction(desired) - Fraction(held) - Fraction(committed))',
         'remaining = desired - held - committed'),
    ), 'test_exact_delta_and_magnitude_preserve_a_fractional_position'),
    ('rounded_delta_magnitude', 'sentinel/execution/commands.py', (
        ('return self.remaining.copy_abs()', 'return abs(self.remaining)'),
    ), 'test_exact_delta_and_magnitude_preserve_a_fractional_position'),
    ('rounded_action_product', 'sentinel/execution/target_reprojection.py', (
        ('projected = Fraction(quantity) * projected_multiplier',
         'projected = Fraction(quantity * Decimal(str(float(projected_multiplier))))'),
    ), 'test_action_product_cannot_round_fractional_intent_into_a_whole_share'),
    ('rounded_surviving_ratio', 'sentinel/execution/target_reprojection.py', (
        ('projected = Fraction(quantity) * projected_multiplier',
         'from sentinel.execution.numeric import display_decimal\n'
         '        projected = Fraction(quantity) * Fraction(display_decimal(projected_multiplier))'),
    ), 'test_cancelled_entry_scaling_keeps_exact_surviving_ratio'),
)


def run(label):
    command = [sys.executable, '-m', 'pytest', *TESTS,
               '-q', '-ra', '--tb=short', '-p', 'no:cacheprovider']
    print(f'CASE {label}: {command}', flush=True)
    result = subprocess.run(command, capture_output=True, text=True)
    print(result.stdout, flush=True)
    print(result.stderr, flush=True)
    return result


def main():
    assert run('positive_controls').returncode == 0
    selected = [m for m in MUTANTS if not sys.argv[1:] or m[0] in sys.argv[1:]]
    assert selected and set(sys.argv[1:]) <= {m[0] for m in MUTANTS}
    for name, filename, changes, expected in selected:
        path = Path(filename)
        original = path.read_bytes()
        changed = original
        for before, after in changes:
            assert changed.count(before.encode()) == 1, (name, before)
            changed = changed.replace(before.encode(), after.encode())
        try:
            path.write_bytes(changed)
            result = run(name)
            assert result.returncode == 1, (name, result.returncode)
            assert 'FAILED ' in result.stdout and expected in result.stdout, name
            assert 'ERROR collecting' not in result.stdout, name
            print(f'DETECTED {name}: {expected}', flush=True)
        finally:
            path.write_bytes(original)
    print(f'PASS: positive controls and {len(selected)}/{len(selected)} quantity mutants', flush=True)


if __name__ == '__main__':
    main()
